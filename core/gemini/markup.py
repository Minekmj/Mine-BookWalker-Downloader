import json
import re
from typing import List, Tuple

from core.ocr_engine import TextSpan

_BOLD_TAG_RE = re.compile(r"(<b>.*?</b>)", re.IGNORECASE | re.DOTALL)
_MD_BOLD_RE = re.compile(r"(\*\*.*?\*\*)")
_BOLD_TAG_TOKEN_RE = re.compile(r"(</?b>)", re.IGNORECASE)
_FT_BLOCK_RE = re.compile(r"<ft\b[^>]*>(.*?)</ft>", re.IGNORECASE | re.DOTALL)
_STRAY_FT_RE = re.compile(r"</?(?:ft|font|span)\b[^>]*>", re.IGNORECASE)
_RUBY_BLOCK_RE = re.compile(r"<ruby\b[^>]*>(.*?)</ruby>", re.IGNORECASE | re.DOTALL)
_RT_RP_RE = re.compile(r"<(?:rt|rp)\b[^>]*>.*?</(?:rt|rp)>", re.IGNORECASE | re.DOTALL)
_STRAY_RUBY_TAG_RE = re.compile(r"</?(?:ruby|rt|rp|font|span)\b[^>]*>", re.IGNORECASE)


def strip_ft_tags(text: str) -> str:
    if not text or "<" not in text:
        return text
    return _STRAY_FT_RE.sub("", text)


def parse_inline_bold_spans(text: str, whole_bold: bool = False) -> List[TextSpan]:
    text = strip_ft_tags(text)
    if "<b>" in text.lower():
        parts = _BOLD_TAG_RE.split(text)
        spans: List[TextSpan] = []
        for p in parts:
            if not p:
                continue
            low = p.lower()
            if low.startswith("<b>") and low.endswith("</b>"):
                inner = p[3:-4]
                if inner:
                    spans.append(TextSpan(inner, True))
            else:
                spans.append(TextSpan(p, False))
        return spans or [TextSpan(text, whole_bold)]

    if "**" in text:
        parts = _MD_BOLD_RE.split(text)
        spans = []
        for p in parts:
            if not p:
                continue
            if p.startswith("**") and p.endswith("**") and len(p) > 4:
                spans.append(TextSpan(p[2:-2], True))
            else:
                spans.append(TextSpan(p, False))
        return spans or [TextSpan(text, whole_bold)]

    return [TextSpan(text, whole_bold)]


def split_merged_paragraph_lines(raw_text: str) -> List[str]:
    result: List[str] = []
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        out: List[str] = []
        depth = 0
        in_bold = False
        i = 0
        n = len(line)
        while i < n:
            if line[i] == "<":
                m = _BOLD_TAG_TOKEN_RE.match(line, i)
                if m:
                    tag = m.group(1)
                    in_bold = not tag.lower().startswith("</")
                    out.append(tag)
                    i = m.end()
                    continue
            ch = line[i]
            out.append(ch)
            if ch in ("「", "『"):
                depth += 1
                i += 1
                continue
            if ch in ("」", "』"):
                if depth > 0:
                    depth -= 1
                if depth == 0:
                    j = i + 1
                    while j < n and line[j] in (" ", "\t", "\u3000"):
                        j += 1
                    next_ch = line[j] if j < n else ""
                    if next_ch in ("「", "『"):
                        if in_bold:
                            out.append("</b>")
                        out.append("\n")
                        if in_bold:
                            out.append("<b>")
                        i = j
                        continue
                i += 1
                continue
            if ch in ("。", "！", "？", "!", "?") and depth == 0:
                j = i + 1
                if j < n and line[j] == "\u3000":
                    while j < n and line[j] in (" ", "\t", "\u3000"):
                        j += 1
                    if j < n:
                        if in_bold:
                            out.append("</b>")
                        out.append("\n")
                        if in_bold:
                            out.append("<b>")
                        i = j
                        continue
                k = i + 1
                while k < n and line[k] in (" ", "\t", "\u3000"):
                    k += 1
                if k < n and line[k] in ("「", "『"):
                    if in_bold:
                        out.append("</b>")
                    out.append("\n")
                    if in_bold:
                        out.append("<b>")
                    i = k
                    continue
            i += 1
        joined = "".join(out)
        for sub in joined.splitlines():
            cleaned = sub.strip()
            if cleaned and cleaned not in ("<b></b>", "<b>", "</b>"):
                result.append(cleaned)
    return result


def extract_ft_segments(raw_text: str) -> List[Tuple[str, bool]]:
    if not raw_text:
        return []
    if "<ft" not in raw_text.lower():
        return [(line, False) for line in split_merged_paragraph_lines(raw_text)]
    segments: List[Tuple[str, bool]] = []
    pos = 0
    in_bold = False
    for match in _FT_BLOCK_RE.finditer(raw_text):
        before = raw_text[pos:match.start()]
        if before:
            clean_before = strip_ft_tags(before)
            for tag_m in _BOLD_TAG_TOKEN_RE.finditer(clean_before):
                in_bold = not tag_m.group(1).lower().startswith("</")
            for line in split_merged_paragraph_lines(clean_before):
                segments.append((line, False))
        inner = strip_ft_tags(match.group(1)).strip()
        if inner:
            if in_bold and "<b" not in inner.lower():
                inner = f"<b>{inner}</b>"
            for tag_m in _BOLD_TAG_TOKEN_RE.finditer(match.group(1)):
                in_bold = not tag_m.group(1).lower().startswith("</")
            for sub in inner.splitlines():
                s = sub.strip()
                if s and s not in ("<b></b>", "<b>", "</b>"):
                    segments.append((s, True))
        pos = match.end()
    tail = raw_text[pos:]
    if tail:
        clean_tail = strip_ft_tags(tail)
        for line in split_merged_paragraph_lines(clean_tail):
            segments.append((line, False))
    return segments


def _is_rate_limit_error(exc: Exception) -> bool:
    s = str(exc).lower()
    return any(tok in s for tok in ("429", "resource_exhausted", "rate limit", "quota", "too many requests"))


def _is_json_parse_error(exc: Exception) -> bool:
    if isinstance(exc, json.JSONDecodeError):
        return True
    s = str(exc).lower()
    return any(
        tok in s
        for tok in (
            "unterminated",
            "expecting value",
            "expecting ','",
            "expecting ':'",
            "delimiter",
            "control character",
            "extra data",
            "invalid \\escape",
            "jsondecodeerror",
        )
    )


def _is_transient_gemini_error(exc: Exception) -> bool:
    if _is_rate_limit_error(exc):
        return True
    s = str(exc).lower()
    return any(
        tok in s
        for tok in (
            "503", "unavailable", "high demand", "overloaded",
            "500", "502", "504", "internal",
            "timeout", "timed out", "connection", "reset", "temporarily",
            "empty", "비어",
        )
    )


def _has_repetition_loop(text: str) -> bool:
    if len(text) < 80:
        return False
    return bool(re.search(r"(.{12,40})\1{4,}", text))


def strip_ruby_tags(text: str) -> str:
    if not text or "<" not in text:
        return text

    def _repl(m):
        inner = _RT_RP_RE.sub("", m.group(1))
        return _STRAY_RUBY_TAG_RE.sub("", inner)

    cleaned = _RUBY_BLOCK_RE.sub(_repl, text)
    cleaned = _RT_RP_RE.sub("", cleaned)
    cleaned = _STRAY_RUBY_TAG_RE.sub("", cleaned)
    return cleaned


def _loads_json_relaxed(raw_text: str):
    text = (raw_text or "").strip()
    m = re.search(r"\{[\s\S]*\}", text)
    candidate = m.group(0) if m else text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as orig_exc:
        repaired = re.sub(r",(\s*[}\]])", r"\1", candidate)
        repaired = re.sub(r'([}\]0-9]|true|false|null)\s+(?=["{\[])', r"\1, ", repaired)
        repaired = re.sub(r'"\s+(?="[^"]+"\s*:)', '", ', repaired)
        repaired = re.sub(r'"\s+(?=["{\[])', '", ', repaired)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            try:
                obj, _ = json.JSONDecoder().raw_decode(repaired)
                return obj
            except Exception:
                raise orig_exc
