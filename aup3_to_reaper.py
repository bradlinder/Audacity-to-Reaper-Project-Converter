#!/usr/bin/env python3
"""aup3-to-reaper legacy entrypoint (forwarder to audacity_to_reaper)."""

import sys
from audacity_to_reaper.cli import main

if __name__ == "__main__":
    sys.exit(main())
