#!/usr/bin/env python3
"""Run the bundled Competitor Daily without changing the user's working directory."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path


def runtime_root(skill_dir: Path) -> Path:
    bundled = skill_dir / "runtime"
    if (bundled / "contest_daily" / "__main__.py").is_file():
        return bundled
    # A source checkout is also a supported installation source.
    for ancestor in skill_dir.parents:
        if (ancestor / "contest_daily" / "__main__.py").is_file():
            return ancestor
    raise RuntimeError(
        "未找到 Competitor Daily 运行程序。请安装完整发布包，"
        "或从包含 contest_daily 的完整源码仓库运行。"
    )


def main() -> None:
    if sys.version_info < (3, 11):
        raise SystemExit("Competitor Daily 需要 Python 3.11 或更新版本。")
    try:
        root = runtime_root(Path(__file__).resolve().parents[1])
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    sys.path.insert(0, str(root))
    runpy.run_module("contest_daily", run_name="__main__")


if __name__ == "__main__":
    main()
