"""三层热词：platform / industry / tenant，按文件 mtime 热更新。"""

from __future__ import annotations

from pathlib import Path

_LAYER_FILES = ("platform.txt", "industry.txt", "tenant.txt")
_cache_key: tuple[tuple[str, float], ...] | None = None
_cache_words: list[str] = []


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return -1.0


def _read_words(path: Path) -> list[str]:
    if not path.is_file():
        return []
    words: list[str] = []
    text = path.read_text(encoding="utf-8")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        words.append(line)
    return words


def load_hotwords(hotwords_dir: Path) -> list[str]:
    """合并三层词表，保序去重。文件变更后下次调用自动重载。"""
    global _cache_key, _cache_words
    paths = [hotwords_dir / name for name in _LAYER_FILES]
    key = tuple((str(path), _mtime(path)) for path in paths)
    if key == _cache_key:
        return list(_cache_words)

    seen: set[str] = set()
    merged: list[str] = []
    for path in paths:
        for word in _read_words(path):
            if word in seen:
                continue
            seen.add(word)
            merged.append(word)
    _cache_key = key
    _cache_words = merged
    return list(merged)


def hotword_string(hotwords_dir: Path, override: str = "") -> str:
    extra = [item for item in override.split() if item]
    if extra:
        base = load_hotwords(hotwords_dir)
        seen = set(base)
        merged = list(base)
        for word in extra:
            if word not in seen:
                seen.add(word)
                merged.append(word)
        return " ".join(merged)
    return " ".join(load_hotwords(hotwords_dir))
