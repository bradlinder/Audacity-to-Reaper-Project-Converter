"""aup3-to-reaper backward compatibility shim.

Redirects imports to the renamed package: audacity_to_reaper.
"""

from audacity_to_reaper import *
from audacity_to_reaper import (
    AudacityProject,
    Clip,
    Effect,
    Marker,
    Region,
    Track,
    convert_aup3_to_reaper,
    convert_project,
)
