"""Package execution entry point for python -m aup3_to_reaper."""

import sys
from .cli import main

if __name__ == "__main__":
    sys.exit(main())
