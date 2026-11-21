import hashlib
import html
import io
import re
from typing import List

from core.epub.patterns import INVALID_XML_RE, PAGE_SUFFIX_RE
from core.ocr_engine import OCRParagraph, TextSpan

RUBY_BLOCK_RE = re.compile(r"<ruby\b[^>]*>(.*?)</ruby>", re.I | re.S)
RT_RP_RE = re.compile(r"<(?:rt|rp)\b[^>]*>.*?</(?:rt|rp)>", re.I | re.S)
STRAY_RUBY_RE = re.compile(r"</?(?:ruby|rt|rp|ft)\b[^>]*>", re.I)


def _clean_ruby(text: str) -> str:
    if not text or "<" not in text:
        return text
    value = RUBY_BLOCK_RE.sub(lambda match: STRAY_RUBY_RE.sub("", RT_RP_RE.sub("", match.group(1))), text)
    return STRAY_RUBY_RE.sub("", RT_RP_RE.sub("", value))


def _xml_safe(text: str) -> str:
    return html.escape(INVALID_XML_RE.sub("", _clean_ruby(text or "")), quote=True)


def _plain_key(text: str) -> str:
    return re.sub(r"[\s　\\-‐‑‒–—:：,，.。・…⋯]+", "", _clean_ruby(text or "")).casefold()


def _image_bytes(image) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def _image_digest(image) -> str:
    return hashlib.sha256(_image_bytes(image)).hexdigest()


def _copy_spans(paragraph: OCRParagraph) -> List[TextSpan]:
    return [TextSpan(_clean_ruby(span.text), span.is_bold) for span in paragraph.spans]


def _render_spans_html(spans: List[TextSpan]) -> str:
    return "".join(f"<strong>{_xml_safe(span.text)}</strong>" if span.is_bold else _xml_safe(span.text) for span in spans)


def _toc_text(spans: List[TextSpan]) -> str:
    value = _clean_ruby("".join(span.text for span in spans)).strip()
    return PAGE_SUFFIX_RE.sub("", value).strip(" .…⋯・\t　")