"""转写后处理：谐音映射、英文大小写、可选 ITN、空白整理。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_cache_path: str | None = None
_cache_mtime: float = -1.0
_cache_rules: dict[str, Any] = {"homophones": [], "english_case": {}}

_CN_DIGITS = {
    "零": "0",
    "〇": "0",
    "一": "1",
    "二": "2",
    "三": "3",
    "四": "4",
    "五": "5",
    "六": "6",
    "七": "7",
    "八": "8",
    "九": "9",
}
_CN_NUMBER_RE = re.compile(r"[零〇一二三四五六七八九]{2,}")
_EN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return -1.0


def _load_rules(path: Path) -> dict[str, Any]:
    global _cache_path, _cache_mtime, _cache_rules
    current = _mtime(path)
    if _cache_path == str(path) and _cache_mtime == current:
        return _cache_rules
    rules: dict[str, Any] = {"homophones": [], "english_case": {}}
    if path.is_file():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            raw_pairs = loaded.get("homophones") or []
            pairs: list[tuple[str, str]] = []
            if isinstance(raw_pairs, list):
                for item in raw_pairs:
                    if not isinstance(item, dict):
                        continue
                    pattern = str(item.get("pattern") or "").strip()
                    replace = str(item.get("replace") or "")
                    if pattern:
                        pairs.append((pattern, replace))
            case_map = loaded.get("english_case") or {}
            english_case = {
                str(key): str(value)
                for key, value in case_map.items()
                if str(key).strip()
            } if isinstance(case_map, dict) else {}
            rules = {"homophones": pairs, "english_case": english_case}
    _cache_path = str(path)
    _cache_mtime = current
    _cache_rules = rules
    return rules


def _apply_homophones(text: str, pairs: list[tuple[str, str]]) -> str:
    result = text
    for pattern, replace in pairs:
        result = re.sub(pattern, replace, result, flags=re.IGNORECASE)
    return result


def _apply_english_case(text: str, case_map: dict[str, str]) -> str:
    if not case_map:
        return text
    lookup = {key.lower(): value for key, value in case_map.items()}

    def _replace(match: re.Match[str]) -> str:
        token = match.group(0)
        return lookup.get(token.lower(), token)

    return _EN_TOKEN_RE.sub(_replace, text)


def _apply_itn(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        return "".join(_CN_DIGITS.get(ch, ch) for ch in match.group(0))

    return _CN_NUMBER_RE.sub(_replace, text)


def _normalize_spaces(text: str) -> str:
    return _MULTI_SPACE_RE.sub(" ", text).strip()


def postprocess_text(
    text: str,
    replacements_file: Path,
    *,
    enabled: bool = True,
    itn_enabled: bool = True,
) -> str:
    if not enabled:
        return text.strip()
    rules = _load_rules(replacements_file)
    result = _apply_homophones(text, rules["homophones"])
    result = _apply_english_case(result, rules["english_case"])
    if itn_enabled:
        result = _apply_itn(result)
    return _normalize_spaces(result)
