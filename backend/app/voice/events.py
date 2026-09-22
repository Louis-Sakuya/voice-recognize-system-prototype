"""浏览器与云端之间的统一识别事件。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TranscriptEvent:
    kind: str
    text: str

    def as_message(self) -> dict[str, str]:
        return {"type": self.kind, "text": self.text}
