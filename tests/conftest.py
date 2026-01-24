"""
Pytest configuration for autonomous editor tests.

This file is automatically loaded by pytest before collecting tests.
"""

import sys
import os
from pathlib import Path

# Add src directory to Python path - use absolute path
_project_root = Path(__file__).parent.parent.absolute()
_src_path = str(_project_root / "src")

if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

# Also set PYTHONPATH for any subprocesses
os.environ["PYTHONPATH"] = _src_path + os.pathsep + os.environ.get("PYTHONPATH", "")
