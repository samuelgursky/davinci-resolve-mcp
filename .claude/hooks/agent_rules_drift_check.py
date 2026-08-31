#!/usr/bin/env python3
import os
import runpy
from pathlib import Path

os.environ["DAVINCI_AGENT_HOST"] = "claude"
runpy.run_path(str(Path(__file__).resolve().parents[2] / ".agents/hooks/agent_rules_drift_check.py"), run_name="__main__")
