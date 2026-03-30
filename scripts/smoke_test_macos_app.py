from __future__ import annotations

import sys
from pathlib import Path

from video2prompt.packaged_smoke import smoke_test_app


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        return 1
    return smoke_test_app(Path(argv[1]))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
