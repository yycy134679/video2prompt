from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_app_can_bootstrap_src_path_without_pythonpath() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    code = """
import runpy
import sys
import types

streamlit = types.ModuleType("streamlit")
streamlit.cache_resource = lambda func: func
sys.modules["streamlit"] = streamlit

runpy.run_path("app.py", run_name="app_under_test")
"""

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
