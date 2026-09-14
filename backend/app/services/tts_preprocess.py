"""朗读前处理：去 Markdown、读法词典、分句。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_cache_path: str | None = None
_cache_mtime: float = -1.0
_cache_readings: list[tuple[str, str]] = []

_FENCE_RE = re.compile(r"```[\s\S]*?```")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)|(?<!_)_([^_]+)_(?!_)")
_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;\n])")
_COMMA_SPLIT_RE = re.compile(r"(?<=[，,、])")

MAX_CHUNK_CHARS = 240
SYNTH_GROUP_CHARS = 320


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return -1.0


def _load_readings(path: Path) -> list[tuple[str, str]]:
    global _cache_path, _cache_mtime, _cache_readings
    current = _mtime(path)
    if _cache_path == str(path) and _cache_mtime == current:
        return _cache_readings
    pairs: list[tuple[str, str]] = []
    if path.is_file():
        loaded: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw_pairs = loaded.get("readings") if isinstance(loaded, dict) else []
        if isinstance(raw_pairs, list):
            for item in raw_pairs:
                if not isinstance(item, dict):
                    continue
                pattern = str(item.get("pattern") or "").strip()
                replace = str(item.get("replace") or "")
                if pattern:
                    pairs.append((pattern, replace))
    _cache_path = str(path)
    _cache_mtime = current
    _cache_readings = pairs
    return pairs


def strip_markdown(text: str) -> str:
    result = _FENCE_RE.sub("代码省略。", text)
    result = _IMAGE_RE.sub(lambda match: match.group(1) or "", result)
    result = _LINK_RE.sub(r"\1", result)
    result = _INLINE_CODE_RE.sub(r"\1", result)
    result = _BOLD_RE.sub(lambda match: match.group(1) or match.group(2) or "", result)
    result = _ITALIC_RE.sub(lambda match: match.group(1) or match.group(2) or "", result)
    result = _HEADING_RE.sub("", result)
    return result


def apply_readings(text: str, readings_file: Path) -> str:
    result = text
    for pattern, replace in _load_readings(readings_file):
        result = re.sub(pattern, replace, result, flags=re.IGNORECASE)
    return result


def _split_long_piece(piece: str) -> list[str]:
    if len(piece) <= MAX_CHUNK_CHARS:
        return [piece] if piece else []
    parts = [item.strip() for item in _COMMA_SPLIT_RE.split(piece) if item.strip()]
    chunks: list[str] = []
    buf = ""
    for part in parts or [piece]:
        if buf and len(buf) + len(part) > MAX_CHUNK_CHARS:
            chunks.append(buf)
            buf = part
        else:
            buf = f"{buf}{part}" if buf else part
        if len(buf) > MAX_CHUNK_CHARS:
            while len(buf) > MAX_CHUNK_CHARS:
                chunks.append(buf[:MAX_CHUNK_CHARS])
                buf = buf[MAX_CHUNK_CHARS:]
    if buf:
        chunks.append(buf)
    return chunks


def split_sentences(text: str) -> list[str]:
    pieces = [item.strip() for item in _SENTENCE_SPLIT_RE.split(text) if item.strip()]
    chunks: list[str] = []
    for piece in pieces:
        chunks.extend(_split_long_piece(piece))
    return chunks


def preprocess_text(text: str, readings_file: Path) -> str:
    result = strip_markdown(text)
    result = apply_readings(result, readings_file)
    result = _MULTI_SPACE_RE.sub(" ", result.replace("\r\n", "\n")).strip()
    return result


def merge_for_synthesis(text: str) -> list[str]:
    """CosyVoice 一次推理开销很大，短段不要拆成多次调用。"""
    spoken = text.strip()
    if not spoken:
        return []
    if len(spoken) <= SYNTH_GROUP_CHARS:
        return [spoken]
    groups: list[str] = []
    buf = ""
    for piece in split_sentences(spoken):
        if buf and len(buf) + len(piece) > SYNTH_GROUP_CHARS:
            groups.append(buf)
            buf = piece
        else:
            buf = f"{buf}{piece}" if buf else piece
    if buf:
        groups.append(buf)
    return groups
