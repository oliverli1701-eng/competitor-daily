#!/usr/bin/env python3
"""Install this skill only when explicitly run; never replace an existing skill."""
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


def install(source: Path, target: Path) -> Path:
    source, target = source.resolve(), target.expanduser().resolve()
    if not (source / "SKILL.md").is_file():
        raise ValueError("安装源缺少 SKILL.md，请使用完整技能包。")
    if not (source / "runtime" / "contest_daily" / "__main__.py").is_file():
        raise ValueError("此目录尚未打包运行程序。请下载完整 Skill ZIP，或先运行仓库的发行打包命令。")
    if target.exists():
        raise ValueError(f"目标已存在，为保留你的文件，未做覆盖：{target}")
    if target == source or source in target.parents:
        raise ValueError("安装目标不能位于源技能目录内部。")
    if any(path.is_symlink() for path in source.rglob("*")):
        raise ValueError("技能包包含符号链接，请使用官方发行包。")
    target.parent.mkdir(parents=True, exist_ok=True)
    ignored = shutil.ignore_patterns("__pycache__", "*.pyc", ".env", ".git", ".venv", "data", "reports")
    shutil.copytree(source, target, ignore=ignored)
    return target


def main() -> None:
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    parser = argparse.ArgumentParser(description="将完整竞赛日报机 Skill 安装到指定目录；已有目录不会被覆盖。")
    parser.add_argument("--target", type=Path, default=codex_home / "skills" / "competitor-daily", help="完整的目标技能目录，默认 CODEX_HOME/skills/competitor-daily")
    args = parser.parse_args()
    try:
        target = install(Path(__file__).resolve().parents[1], args.target)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"安装未完成：{exc}\n")
    print(f"已安装：{target}")
    print("在新的 Agent 对话中使用 $competitor-daily，或让 Agent 读取该目录的 SKILL.md。")
    print("WorkBuddy 用户也可直接在技能页面通过「添加技能 → 上传技能」导入发行 ZIP。")


if __name__ == "__main__":
    main()
