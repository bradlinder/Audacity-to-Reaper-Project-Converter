#!/usr/bin/env python3
"""Audacity to REAPER Project Converter - CLI Entrypoint."""

import sys
from audacity_to_reaper.cli import main

if __name__ == "__main__":
    sys.exit(main())
