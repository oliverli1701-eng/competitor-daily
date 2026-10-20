"""User-owned report identity, shared by HTML, Markdown and PDF renderers.

Profiles only control presentation. Competition recognition and research scopes
continue to come from the imported catalog and source registry.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit


DEFAULT_PROFILE = {
    "schema_version": 1,
    "university": "兰州大学",
    "college": "信息科学与工程学院",
    "report_title": "竞赛日报",
    "english_title": "COMPETITION BRIEF",
    "brand_name": "竞赛情报",
    "subtitle": "学科竞赛追踪",
    "accent_color": "",
    "website_url": "",
    "footer_text": "",
}

_TEXT_LIMITS = {
    "university": 100, "college": 100, "report_title": 40,
    "english_title": 100, "brand_name": 40, "subtitle": 150,
    "footer_text": 200,
}


def normalize_profile(value=None):
    """Return a validated copy; reject malformed presentation configuration.

    Unknown keys are preserved, allowing later adapters to add their own fields.
    Text remains plain text here and is escaped at each output boundary.
    """
    if value is None:
        return dict(DEFAULT_PROFILE)
    if not isinstance(value, dict):
        raise ValueError("profile 必须是 JSON 对象")
    version = value.get("schema_version", 1)
    if type(version) is not int or version != 1:
        raise ValueError("profile.schema_version 目前仅支持 1")
    result = {**DEFAULT_PROFILE, **value, "schema_version": 1}
    if "site_url" in value and "website_url" not in value:
        result["website_url"] = value["site_url"]
    for field, limit in _TEXT_LIMITS.items():
        text = result[field]
        if not isinstance(text, str):
            raise ValueError(f"profile.{field} 必须是文本")
        text = text.strip()
        if any(ord(character) < 32 for character in text) or len(text) > limit:
            raise ValueError(f"profile.{field} 不能包含控制字符，且最多 {limit} 字")
        if field in ("report_title", "brand_name") and not text:
            raise ValueError(f"profile.{field} 不能为空")
        result[field] = text
    color = result["accent_color"]
    if not isinstance(color, str) or (color and not re.fullmatch(r"#[0-9a-fA-F]{6}", color)):
        raise ValueError("profile.accent_color 应为 #RRGGBB，或留空使用默认主题")
    result["accent_color"] = color.lower()
    website = result["website_url"]
    if not isinstance(website, str) or len(website) > 500:
        raise ValueError("profile.website_url 必须是网址文本，最多 500 字")
    website = website.strip()
    if website:
        try:
            parsed = urlsplit(website)
            valid = parsed.scheme in ("http", "https") and parsed.hostname and not parsed.username and not parsed.password
        except ValueError:
            valid = False
        if not valid or any(ord(character) < 33 for character in website):
            raise ValueError("profile.website_url 仅支持无用户名密码的 HTTP(S) 网址")
    result["website_url"] = website
    return result


def load_profile(root: Path):
    """Read config/profile.json; old workspaces keep their original identity."""
    path = Path(root) / "config" / "profile.json"
    if not path.is_file():
        return normalize_profile()
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ValueError(f"无法读取学院配置 {path}: {error}") from error
    return normalize_profile(value)


def institution_name(profile):
    return profile["university"] + profile["college"]


def profile_css(profile):
    """Only validated hex colors enter CSS; keep urgency colors unchanged."""
    color = profile["accent_color"]
    if not color:
        return ""
    rgb = tuple(int(color[index:index + 2], 16) for index in (1, 3, 5))
    def blend(background, fraction):
        return "#" + "".join(f"{round(value * fraction + background * (1 - fraction)):02x}" for value in rgb)
    light = f"--accent:{color};--accent-soft:{blend(255, .08)};--accent-line:{blend(255, .27)};"
    dark = f"--accent:{blend(255, .60)};--accent-soft:{blend(18, .17)};--accent-line:{blend(18, .40)};"
    return (f":root{{{light}}}:root[data-theme='dark']{{{dark}}}"
            f"@media(prefers-color-scheme:dark){{:root:not([data-theme='light']){{{dark}}}}}")
