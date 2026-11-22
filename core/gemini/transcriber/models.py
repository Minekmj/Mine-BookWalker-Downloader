from dataclasses import dataclass
from typing import Callable, List, Union

from PIL import Image

from core.ocr import OCRParagraph

ImageOrLoader = Union[Image.Image, Callable[[], Image.Image]]


@dataclass
class GeminiPageResult:
    page_no: int
    paragraphs: List[OCRParagraph]
    used_temp: float = 0.0
    used_model: str = ""
    error_reason: str = ""
    ink_ratio: float = -1.0
