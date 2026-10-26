#!/usr/bin/env python3
"""Entry point kept at the v2 path so 打开审核.command and the daily launchd job keep working."""

import sys

from capcreator.cli import main

if __name__ == "__main__":
    sys.exit(main())
