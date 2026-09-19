#!/usr/bin/env python3
"""Compatibility entry point for the real account API gate; no LID1 stub checks."""
from pathlib import Path
import runpy
import sys

if len(sys.argv) == 2:
    sys.argv.append(str(Path(sys.argv[1]).with_name("account-fixture")))
runpy.run_path(str(Path(__file__).with_name("check_accounts.py")), run_name="__main__")
