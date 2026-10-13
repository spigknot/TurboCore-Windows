"""Source-run entry point; packaged builds dispatch through main's worker flag."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from turbocore.clock_broker import run_worker

if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(2)
    run_worker(int(sys.argv[1]), sys.argv[2], int(sys.argv[3]))
