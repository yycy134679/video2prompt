from __future__ import annotations

import sys
from pathlib import Path

from video2prompt.packaged_module_guard import scan_artifact_paths


def main(argv: list[str]) -> int:
    scan_artifact_paths([Path(arg) for arg in argv[1:]])
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
