"""High-level converter engine coordinating parser, audio extractor, RPP writer, and FX mapper."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .audio_extractor import AudioExtractor
from .aup3_reader import AUP3Reader
from .fx_mapper import FXMapper
from .models import AudacityProject
from .report_generator import ReportGenerator
from .rpp_generator import RPPGenerator

logger = logging.getLogger(__name__)


@dataclass
class ConversionResult:
    """Detailed result of an Audacity to REAPER conversion run."""
    success: bool
    project_name: str
    output_dir: Path
    rpp_file: Optional[Path] = None
    report_file: Optional[Path] = None
    fx_script_file: Optional[Path] = None
    media_dir: Optional[Path] = None
    total_tracks: int = 0
    total_clips: int = 0
    total_extracted_files: int = 0
    total_duration_seconds: float = 0.0
    envelope_mode: str = "clip"
    embed_fx: bool = True
    embedded_fx_count: int = 0
    is_dry_run: bool = False
    warnings: List[str] = None
    unsupported_features: List[str] = None
    extraction_summary: Dict[str, Any] = None


def convert_aup3_to_reaper(
    aup3_path: str | Path,
    output_dir: Optional[str | Path] = None,
    extract_fx_script: bool = True,
    embed_fx: bool = True,
    envelope_mode: str = "clip",
    dry_run: bool = False,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> ConversionResult:
    """Convert an Audacity 3+ project (.aup3) into a REAPER project (.rpp).
    
    Args:
        aup3_path: Path to the source .aup3 SQLite project file.
        output_dir: Directory where the converted project, media, and reports will be saved.
                    If omitted, defaults to a folder named `{stem}_reaper` next to the .aup3.
        extract_fx_script: Whether to generate the companion `session_load_fx.lua` script.
        embed_fx: Whether to embed <FXCHAIN> chunks directly into REAPER track blocks in .rpp.
        envelope_mode: Volume envelope target: 'clip' (take envelope) or 'track' (track automation lane).
        dry_run: If True, inspects and logs the conversion plan without writing any files.
        progress_callback: Optional callback receiving human-readable status updates.
    
    Returns:
        ConversionResult dataclass summarizing the outcome and file paths.
    """
    def log_msg(msg: str) -> None:
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    source_path = Path(aup3_path).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    stem = source_path.stem
    if output_dir is None:
        target_dir = source_path.parent / f"{stem}_reaper"
    else:
        target_dir = Path(output_dir).resolve()

    log_msg(f"Parsing Audacity project database: {source_path.name}")
    reader = AUP3Reader(source_path)
    project = reader.parse_project()

    log_msg(
        f"Parsed {len(project.tracks)} tracks, {project.total_clips} clips, "
        f"{len(project.markers)} markers, {len(project.regions)} regions."
    )

    media_dir = target_dir / "media"
    rpp_path = target_dir / f"{stem}.rpp"
    report_path = target_dir / f"{stem}_MIGRATION_REPORT.md"
    fx_script_path = target_dir / f"{stem}_load_fx.lua" if extract_fx_script else None

    # Handle dry-run mode
    if dry_run:
        log_msg("[DRY RUN] Simulating conversion without writing to disk...")
        mock_summary = {
            "media_dir": str(media_dir),
            "total_files": project.total_clips,
            "total_bytes": 0,
            "total_extracted_duration": project.total_duration,
            "files": [],
        }
        return ConversionResult(
            success=True,
            project_name=project.name,
            output_dir=target_dir,
            rpp_file=rpp_path,
            report_file=report_path,
            fx_script_file=fx_script_path,
            media_dir=media_dir,
            total_tracks=len(project.tracks),
            total_clips=project.total_clips,
            total_extracted_files=project.total_clips,
            total_duration_seconds=project.total_duration,
            envelope_mode=envelope_mode,
            embed_fx=embed_fx,
            embedded_fx_count=sum(len(t.effects) for t in project.tracks) if embed_fx else 0,
            is_dry_run=True,
            warnings=project.warnings,
            unsupported_features=project.unsupported_features,
            extraction_summary=mock_summary,
        )

    # 1. Extract audio sample blocks into clean WAV files
    log_msg(f"Extracting media blocks to: {media_dir}")
    extractor = AudioExtractor(source_path, media_dir)
    extraction_summary = extractor.extract_all(project)
    log_msg(
        f"Wrote {extraction_summary['total_files']} audio files "
        f"({extraction_summary['total_bytes'] / (1024*1024):.2f} MB)"
    )

    # 2. Generate REAPER .rpp project file
    embedded_fx_total = sum(len(t.effects) for t in project.tracks) if embed_fx else 0
    log_msg(
        f"Generating REAPER project file: {rpp_path.name} "
        f"(envelope_mode={envelope_mode}, embed_fx={embed_fx}, fx_count={embedded_fx_total})"
    )
    rpp_gen = RPPGenerator(project, rpp_path, envelope_mode=envelope_mode, embed_fx=embed_fx)
    rpp_gen.write()

    # 3. Generate ReaScript FX loader script if requested
    if extract_fx_script:
        log_msg(f"Generating ReaScript FX Loader: {fx_script_path.name}")
        fx_mapper = FXMapper(project)
        fx_mapper.generate_lua_script(fx_script_path)

    # 4. Generate comprehensive migration report
    log_msg(f"Generating Migration Report: {report_path.name}")
    report_gen = ReportGenerator(project, target_dir, envelope_mode=envelope_mode, embed_fx=embed_fx)
    report_gen.write(extraction_summary, filename=report_path.name)

    log_msg("Conversion successfully completed!")

    return ConversionResult(
        success=True,
        project_name=project.name,
        output_dir=target_dir,
        rpp_file=rpp_path,
        report_file=report_path,
        fx_script_file=fx_script_path,
        media_dir=media_dir,
        total_tracks=len(project.tracks),
        total_clips=project.total_clips,
        total_extracted_files=extraction_summary["total_files"],
        total_duration_seconds=project.total_duration,
        envelope_mode=envelope_mode,
        embed_fx=embed_fx,
        embedded_fx_count=embedded_fx_total,
        is_dry_run=False,
        warnings=project.warnings,
        unsupported_features=project.unsupported_features,
        extraction_summary=extraction_summary,
    )


# Aliases for multi-format and rebrand compatibility
convert_audacity_to_reaper = convert_aup3_to_reaper
convert_project = convert_aup3_to_reaper
