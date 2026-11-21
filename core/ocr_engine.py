import re
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
        )


HARD_SENTENCE_ENDINGS = ("。", "！", "？", "」", "』", "】", "）", "!", "?", ".")
DIALOGUE_STARTS = ("「", "『", "【", "（")

SCENE_BREAK_PATTERN = re.compile(
    r"^[\s■□◆◇●○◎▲△▼▽★☆＊*※・･\-－―─━┃═＿_=＝~〜～†‡§¶◊◈✦✧♠♥♣♦❖❦❧·•]+$"
)
AMBIGUOUS_SINGLE_SYMBOL = {"-", "－", "―", "─", "・", ".", "=", "I", "l", "1", "o", "O", "口", "□", "■", "◆", "◇", "●"}
KATAKANA_DASH_RE = re.compile(r"(?<=[\u30A1-\u30FA\u30FC])1(?=[\u30A1-\u30FA\u30FC]|$|[^\w])")

HEADING_NO_JOIN_RE = re.compile(
    r"^(目次|もくじ|목차|차례|プロローグ|エピローグ|あとがき|序章|終章|幕間|外伝|番外編|"
    r"電子版\s*SS|第[〇一二三四五六七八九十百千0-9０-９]+[章話部節編]|"
    r"제\s*[0-9일이삼사오육칠팔구십]+\s*[장화편부]|Chapter\s+\d+)"
)


def is_scene_break_text(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if t in {".", ",", "。", "、", "・"}:
        return False
    if len(t) == 1 and t in {
        "-", "－", "―", "─", "■", "□", "◆", "◇", "●", "○", "◎",
        "▲", "△", "▼", "▽", "＊", "*", "※", "★", "☆", "♠", "♥", "♣", "♦", "❖",
    }:
        return True
    if len(t) >= 2 and SCENE_BREAK_PATTERN.match(t):
        return True
    return False


def is_heading_like_text(text: str) -> bool:
    t = text.strip()
    if not t or len(t) > 45:
        return False
    if t.endswith(("。", "、", "」", "』")):
        return False
    return bool(HEADING_NO_JOIN_RE.match(t))


def clean_japanese_ocr_artifacts(text: str, language: str = "ja") -> str:
    if language == "ja":
        text = KATAKANA_DASH_RE.sub("ー", text)
    return text