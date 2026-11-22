import re

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
