"""Audacity to REAPER Project Converter.

Converts Audacity projects into Cockos REAPER projects (.rpp).
"""

__version__ = "1.1.0"
__author__ = "Audacity to REAPER Project Converter Developers"

from .converter import convert_aup3_to_reaper
from .models import AudacityProject, Track, Clip, Marker, Region, Effect

# Generic alias for multi-format expansion
convert_project = convert_aup3_to_reaper

__all__ = [
    "convert_aup3_to_reaper",
    "convert_project",
    "AudacityProject",
    "Track",
    "Clip",
    "Marker",
    "Region",
    "Effect",
    "__version__",
]
