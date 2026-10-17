"""Install-free entry point from a standalone clone."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from matlab_harness.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
