#!/usr/bin/env python3
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from ligatus_object_scope import main


if __name__ == "__main__":
    main()
