"""Source-checkout wrapper for the same packaged journey implementation."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from matlab_harness.journey import Journey, main, run_journey

if __name__ == "__main__":
    raise SystemExit(main())
