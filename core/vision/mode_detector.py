from pathlib import Path
from typing import List, Sequence, Tuple

from core.vision.image_utils import load_image_rgb
from core.vision.novel_detector import analyze_novel_page


def sample_indices(total: int) -> List[int]:
    if total <= 0:
        return []
    candidates = [0, total // 4, total // 2, (3 * total) // 4, total - 1]
    result: List[int] = []
    for index in candidates:
        if index not in result:
            result.append(index)
    return result


def detect_folder_mode(paths: Sequence[Path], sensitivity: str = "normal") -> Tuple[str, float, int, int]:
    indices = sample_indices(len(paths))
    if not indices:
        return "novel", 0.0, 0, 0
    illustrations = 0
    for index in indices:
        image = load_image_rgb(paths[index])
        if analyze_novel_page(image, sensitivity=sensitivity).is_illustration:
            illustrations += 1
    ratio = illustrations / len(indices)
    mode = "manga" if ratio > 0.5 else "novel"
    return mode, ratio, illustrations, len(indices)
