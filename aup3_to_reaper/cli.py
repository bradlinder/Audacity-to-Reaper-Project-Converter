"""Command-line interface (CLI) for aup3-to-reaper."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__
from .converter import convert_aup3_to_reaper


def setup_logging(verbose: bool = False) -> None:
    """Configure terminal log formatting."""
    level = logging.DEBUG if verbose else logging.INFO
    format_str = "[%(levelname)s] %(message)s" if not verbose else "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=level, format=format_str, handlers=[logging.StreamHandler(sys.stdout)])


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="aup3-to-reaper",
        description="Convert modern Audacity (.aup3) projects into REAPER (.rpp) projects.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python aup3_to_reaper.py session.aup3
  python aup3_to_reaper.py session.aup3 -o ./reaper_project/
  python aup3_to_reaper.py session.aup3 --extract-fx-script --dry-run
        """,
    )

    parser.add_argument(
        "path_to_aup3",
        type=str,
        nargs="?",
        default=None,
        help="Path to the Audacity 3+ project file (.aup3). If omitted, opens the graphical interface (GUI).",
    )

    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the interactive graphical user interface (GUI).",
    )

    parser.add_argument(
        "-o",
        "--output-dir",
        type=str,
        default=None,
        help="Optional output directory. Defaults to '<session_name>_reaper/' in the same directory.",
    )

    parser.add_argument(
        "--extract-fx-script",
        action="store_true",
        default=True,
        help="Generate companion ReaScript FX loader script (session_load_fx.lua). Enabled by default.",
    )

    parser.add_argument(
        "--no-fx-script",
        dest="extract_fx_script",
        action="store_false",
        help="Disable generating the companion ReaScript FX loader script.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect and print conversion plan without extracting media or writing files.",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose / debug diagnostic output.",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Main CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)

    # Launch GUI if requested or if no positional path provided
    if args.gui or args.path_to_aup3 is None:
        from .gui import launch_gui
        return launch_gui()

    setup_logging(args.verbose)

    input_path = Path(args.path_to_aup3)
    if not input_path.exists():
        sys.stderr.write(f"Error: Project file not found: {input_path}\n")
        return 1

    print("=" * 65)
    print(f" aup3-to-reaper v{__version__} - Audacity to REAPER Converter")
    print("=" * 65)

    try:
        result = convert_aup3_to_reaper(
            aup3_path=input_path,
            output_dir=args.output_dir,
            extract_fx_script=args.extract_fx_script,
            dry_run=args.dry_run,
        )

        print("-" * 65)
        if result.is_dry_run:
            print("[DRY RUN COMPLETE] Project structure inspected successfully:")
            print(f"  * Project Name:      {result.project_name}")
            print(f"  * Target Output:     {result.output_dir}")
            print(f"  * Total Tracks:      {result.total_tracks}")
            print(f"  * Total Clips:       {result.total_clips}")
            print(f"  * Total Duration:    {result.total_duration_seconds:.2f} seconds")
            if result.fx_script_file:
                print(f"  * FX Script Planned: {result.fx_script_file.name}")
            print("-" * 65)
            print("No files written (--dry-run).")
            return 0

        print("[CONVERSION COMPLETE]")
        print(f"  * REAPER Project:     {result.rpp_file}")
        print(f"  * Extracted Media:    {result.media_dir} ({result.total_extracted_files} WAV files)")
        print(f"  * Migration Report:   {result.report_file}")
        if result.fx_script_file:
            print(f"  * ReaScript FX:       {result.fx_script_file}")
        print(f"  * Converted Tracks:   {result.total_tracks}")
        print(f"  * Converted Clips:    {result.total_clips}")
        print(f"  * Project Duration:   {result.total_duration_seconds:.2f} seconds")
        print("=" * 65)
        print("Open the project in REAPER and check the migration report for details.")
        return 0

    except Exception as exc:
        sys.stderr.write(f"\n[FATAL ERROR] {exc}\n")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
