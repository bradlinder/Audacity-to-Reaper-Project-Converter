#!/usr/bin/env python3
"""Audacity to REAPER Project Converter - GUI Entrypoint."""

import sys
from audacity_to_reaper.gui import launch_gui

if __name__ == "__main__":
    sys.exit(launch_gui())
