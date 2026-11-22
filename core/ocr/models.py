from dataclasses import dataclass
from typing import List


@dataclass
class TextSpan:
    text: str
    is_bold: bool = False

    def to_dict(self) -> dict:
        return {"text": self.text, "is_bold": self.is_bold}

    @classmethod
    def from_dict(cls, d: dict) -> "TextSpan":
        return cls(text=d.get("text", ""), is_bold=bool(d.get("is_bold", False)))


@dataclass
class OCRParagraph:
    spans: List[TextSpan]
    ends_open: bool = False
    is_scene_break: bool = False
    is_heading: bool = False
    heading_level: int = 0
    block_type: str = "paragraph"
    reading_order: int = -1
    is_toc_entry: bool = False
    is_toc_candidate: bool = False
    is_bic_candidate: bool = False

    @property
    def plain_text(self) -> str:
        return "".join(s.text for s in self.spans)

    @property
    def is_all_bold(self) -> bool:
        non_empty = [s for s in self.spans if s.text.strip()]
        return bool(non_empty) and all(s.is_bold for s in non_empty)

    def to_dict(self) -> dict:
        return {
            "spans": [s.to_dict() for s in self.spans],
            "ends_open": self.ends_open,
            "is_scene_break": self.is_scene_break,
            "is_heading": self.is_heading,
            "heading_level": self.heading_level,
            "block_type": self.block_type,
            "reading_order": self.reading_order,
            "is_toc_entry": self.is_toc_entry,
            "is_toc_candidate": self.is_toc_candidate,
            "is_bic_candidate": self.is_bic_candidate,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OCRParagraph":
        try:
            heading_level = max(0, min(3, int(d.get("heading_level", 0) or 0)))
        except (TypeError, ValueError):
            heading_level = 0
        try:
            reading_order = int(d.get("reading_order", -1) if d.get("reading_order") is not None else -1)
        except (TypeError, ValueError):
            reading_order = -1
        return cls(
            spans=[TextSpan.from_dict(s) for s in d.get("spans", []) if isinstance(s, dict)],
            ends_open=bool(d.get("ends_open", False)),
            is_scene_break=bool(d.get("is_scene_break", False)),
            is_heading=bool(d.get("is_heading", False)),
            heading_level=heading_level,
            block_type=str(d.get("block_type", "paragraph") or "paragraph"),
            reading_order=reading_order,
            is_toc_entry=bool(d.get("is_toc_entry", False)),
            is_toc_candidate=bool(d.get("is_toc_candidate", False)),
            is_bic_candidate=bool(d.get("is_bic_candidate", False)),
        )
