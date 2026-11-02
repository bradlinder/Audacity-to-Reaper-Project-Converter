#!/usr/bin/env python3
"""aup3-to-reaper GUI legacy entrypoint (forwarder to audacity_to_reaper)."""

import sys
from audacity_to_reaper.gui import launch_gui

if __name__ == "__main__":
    sys.exit(launch_gui())
