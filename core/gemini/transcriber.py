import json
import re
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple, Union

from PIL import Image

from core.gemini.images import _make_labeled_png_bytes
from core.gemini.markup import (
    _is_rate_limit_error,
    _is_transient_gemini_error,
    extract_ft_segments,
    parse_inline_bold_spans,
    strip_ft_tags,
    strip_ruby_tags,
)
from core.gemini.page_stats import compute_page_ink_ratio
from core.gemini.pool import GeminiKeyPool
from core.gemini.prompts import build_transcribe_system_prompt
from core.gemini.review import ReviewMixin
from core.gemini.schema import TRANSCRIBE_SCHEMA
from core.ocr_engine import OCRParagraph, TextSpan, clean_japanese_ocr_artifacts, is_scene_break_text

_HANGUL_CHAR_RE = re.compile(r"[\uAC00-\uD7A3]")
ImageOrLoader = Union[Image.Image, Callable[[], Image.Image]]


@dataclass
class GeminiPageResult:
    page_no: int
    paragraphs: List[OCRParagraph]
    used_temp: float = 0.0
    used_model: str = ""
    error_reason: str = ""
    ink_ratio: float = -1.0


class GeminiTranscriber(ReviewMixin):
    def __init__(
        self,
        api_keys: List[str],
        model_name: str = "gemini-3.1-flash-lite",
        rpm_per_key: int = 10,
        temperature: float = 0.1,
        temp_step: float = 0.25,
        max_retries: int = 3,
        language: str = "ja",
        orientation: str = "vertical",
    ):
        self.pool = GeminiKeyPool(api_keys=api_keys, rpm_per_key=rpm_per_key)
        self.model_name = model_name.strip() or "gemini-3.1-flash-lite"
        self.temperature = max(0.0, min(1.5, float(temperature)))
        self.temp_step = max(0.0, float(temp_step))
        self.max_retries = max(1, int(max_retries))
        self.language = language.lower()
        self.orientation = orientation.lower()

    def get_token_usage(self) -> Dict[str, int]:
        return self.pool.get_usage()

    def _call_batch_once(
        self,
        batch: List[Tuple[int, ImageOrLoader]],
        temperature: float,
        model_override: Optional[str] = None,
        cancelled_fn: Optional[Callable[[], bool]] = None,
    ) -> Dict[int, GeminiPageResult]:
        from google.genai import types

        model_to_use = (model_override or self.model_name).strip()
        contents = []
        mapping_desc = []
        ink_ratios: Dict[int, float] = {}
        for seq_idx, (page_no, img_or_fn) in enumerate(batch, start=1):
            img = img_or_fn() if callable(img_or_fn) else img_or_fn
            ink_ratios[page_no] = compute_page_ink_ratio(img)
            contents.append(f"### IMAGE {seq_idx} (page_no={page_no}) ###")
            contents.append(
                types.Part.from_bytes(
                    data=_make_labeled_png_bytes(img, seq_idx, page_no),
                    mime_type="image/png",
                )
            )
            mapping_desc.append(f"IMAGE {seq_idx} -> page_no={page_no}")

        if self.language == "ja":
            contents.append("各画像を順番通りにそのままJSONへ文字起こししてください（翻訳禁止・原本の日本語のみ出力）：\n" + "\n".join(mapping_desc))
        else:
            contents.append("Transcribe each image strictly in order into JSON:\n" + "\n".join(mapping_desc))

        safety = [
            types.SafetySetting(category=cat, threshold=types.HarmBlockThreshold.BLOCK_NONE)
            for cat in (
                types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
            )
        ]

        config = types.GenerateContentConfig(
            system_instruction=build_transcribe_system_prompt(self.language, self.orientation),
            temperature=float(max(0.0, min(1.5, temperature))),
            max_output_tokens=32768,
            response_mime_type="application/json",
            response_schema=TRANSCRIBE_SCHEMA,
            safety_settings=safety,
        )

        resp = self.pool.generate(
            cancelled_fn=cancelled_fn,
            model=model_to_use,
            contents=contents,
            config=config,
        )

        raw_text = (getattr(resp, "text", None) or "").strip()
        if not raw_text:
            raise ValueError("Gemini 응답이 비어 있습니다 (안전 필터 또는 빈 출력).")

        m = re.search(r"\{[\s\S]*\}", raw_text)
        data = json.loads(m.group(0) if m else raw_text)
        pages_raw = data.get("pages", [])

        seq_to_pno = {seq_idx: p_no for seq_idx, (p_no, _) in enumerate(batch, start=1)}
        expected_set = {p for p, _ in batch}
        parsed_map: Dict[int, GeminiPageResult] = {}

        for p_item in pages_raw:
            p_no = int(p_item.get("page_no", -1))
            img_idx = int(p_item.get("image_index", -1))
            if img_idx in seq_to_pno:
                p_no = seq_to_pno[img_idx]
            elif p_no not in expected_set:
                continue

            ends_open = bool(p_item.get("ends_open", False))
            para_objs: List[OCRParagraph] = []
            raw_paras = p_item.get("paragraphs", [])

            ordered_raw = []
            for idx, para in enumerate(raw_paras):
                if not isinstance(para, dict):
                    continue
                try:
                    reading_order = int(para.get("reading_order", idx))
                except (TypeError, ValueError):
                    reading_order = idx
                txt = clean_japanese_ocr_artifacts(strip_ruby_tags(str(para.get("text", "")).strip()), self.language)
                if txt:
                    ordered_raw.append((reading_order, idx, para, txt))
            if ordered_raw and any(order >= 0 for order, _, _, _ in ordered_raw):
                ordered_raw.sort(key=lambda item: (item[0] if item[0] >= 0 else item[1], item[1]))

            if self.language == "ja" and ordered_raw:
                joined_check = "".join(strip_ft_tags(item[3]) for item in ordered_raw)
                if len(_HANGUL_CHAR_RE.findall(joined_check)) >= 5:
                    raise ValueError(f"p{p_no} OCR 출력에 한국어 번역이 포함되어 재시도합니다.")

            next_order = 0
            for idx, (reading_order, original_idx, para, txt) in enumerate(ordered_raw):
                block_type = str(para.get("block_type", "paragraph") or "paragraph").lower()
                try:
                    heading_level = max(0, min(3, int(para.get("heading_level", 0) or 0)))
                except (TypeError, ValueError):
                    heading_level = 0
                is_heading = bool(para.get("is_heading", False)) or block_type in ("chapter_heading", "section_heading")
                is_toc_entry = bool(para.get("is_toc_entry", False)) or block_type == "toc_entry"
                clean_plain_txt = strip_ft_tags(txt)
                is_sb = bool(para.get("is_scene_break", False)) or block_type == "scene_break" or is_scene_break_text(clean_plain_txt)
                whole_bold = bool(para.get("is_bold", False))
                is_last = idx == len(ordered_raw) - 1

                if is_sb:
                    spans = [TextSpan(re.sub(r"</?b>", "", clean_plain_txt, flags=re.IGNORECASE), False)]
                    para_objs.append(
                        OCRParagraph(
                            spans=spans,
                            ends_open=False,
                            is_scene_break=True,
                            is_heading=is_heading,
                            heading_level=heading_level,
                            block_type=block_type,
                            reading_order=next_order,
                            is_toc_entry=is_toc_entry,
                            is_toc_candidate=False,
                        )
                    )
                    next_order += 1
                elif is_toc_entry or block_type == "toc_title":
                    has_ft = "<ft" in txt.lower()
                    spans = parse_inline_bold_spans(clean_plain_txt, whole_bold=whole_bold)
                    para_objs.append(
                        OCRParagraph(
                            spans=spans,
                            ends_open=(ends_open and is_last),
                            is_scene_break=False,
                            is_heading=is_heading,
                            heading_level=heading_level,
                            block_type=block_type,
                            reading_order=next_order,
                            is_toc_entry=is_toc_entry,
                            is_toc_candidate=has_ft,
                        )
                    )
                    next_order += 1
                else:
                    segments = extract_ft_segments(txt)
                    if not segments:
                        segments = [(clean_plain_txt, "<ft" in txt.lower())]
                    for sub_idx, (sub_txt, seg_is_ft) in enumerate(segments):
                        is_sub_last = sub_idx == len(segments) - 1
                        sub_clean = strip_ft_tags(sub_txt)
                        if not sub_clean.strip():
                            continue
                        spans = parse_inline_bold_spans(sub_clean, whole_bold=whole_bold)
                        seg_heading = is_heading and (seg_is_ft or len(segments) == 1)
                        seg_level = heading_level if seg_heading else 0
                        seg_type = block_type if seg_heading else "paragraph"
                        para_objs.append(
                            OCRParagraph(
                                spans=spans,
                                ends_open=(ends_open and is_last and is_sub_last and not seg_is_ft),
                                is_scene_break=is_scene_break_text(sub_clean),
                                is_heading=seg_heading,
                                heading_level=seg_level,
                                block_type=seg_type,
                                reading_order=next_order,
                                is_toc_entry=False,
                                is_toc_candidate=seg_is_ft or seg_heading,
                            )
                        )
                        next_order += 1

            parsed_map[p_no] = GeminiPageResult(
                page_no=p_no,
                paragraphs=para_objs,
                used_temp=temperature,
                used_model=model_to_use,
                ink_ratio=ink_ratios.get(p_no, -1.0),
            )

        return parsed_map

    def transcribe_batch_resilient(
        self,
        batch: List[Tuple[int, ImageOrLoader]],
        cancelled_fn: Optional[Callable[[], bool]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
        start_temp: Optional[float] = None,
        model_override: Optional[str] = None,
        max_attempts: Optional[int] = None,
    ) -> Tuple[Dict[int, GeminiPageResult], Dict[int, str]]:

        results: Dict[int, GeminiPageResult] = {}
        failures: Dict[int, str] = {}
        pending = list(batch)
        base_temp = self.temperature if start_temp is None else float(start_temp)
        attempts = max(1, int(max_attempts if max_attempts is not None else self.max_retries))

        for attempt in range(1, attempts + 1):
            if not pending or (cancelled_fn and cancelled_fn()):
                break

            cur_temp = round(max(0.0, min(1.5, base_temp + self.temp_step * (attempt - 1))), 4)
            try:
                got = self._call_batch_once(
                    pending,
                    temperature=cur_temp,
                    model_override=model_override,
                    cancelled_fn=cancelled_fn,
                )
                results.update(got)
                pending = [(p, img) for p, img in pending if p not in results]
                if not pending:
                    return results, {}
                if log_cb:
                    log_cb(
                        f"누락 페이지 {[p for p, _ in pending]} 누적 재시도 "
                        f"({attempt}/{attempts}, temp={cur_temp})"
                    )
            except InterruptedError:
                raise
            except Exception as exc:
                err_str = str(exc) or type(exc).__name__
                for p, _ in pending:
                    failures[p] = err_str
                if log_cb:
                    log_cb(
                        f"요청 오류 {[p for p, _ in pending]} (시도 {attempt}/{attempts}, temp={cur_temp}): {err_str}"
                    )
                if not _is_transient_gemini_error(exc) and len(pending) > 1 and attempt >= 2:
                    mid = len(pending) // 2
                    l_res, l_fail = self.transcribe_batch_resilient(
                        pending[:mid], cancelled_fn, log_cb, start_temp=cur_temp, model_override=model_override, max_attempts=3
                    )
                    r_res, r_fail = self.transcribe_batch_resilient(
                        pending[mid:], cancelled_fn, log_cb, start_temp=cur_temp, model_override=model_override, max_attempts=3
                    )
                    results.update(l_res)
                    results.update(r_res)
                    failures.update(l_fail)
                    failures.update(r_fail)
                    return results, {p: f for p, f in failures.items() if p not in results}
                if _is_rate_limit_error(exc):
                    self._sleep_cancelable(0.5, cancelled_fn=cancelled_fn)

        for p, _ in pending:
            if p not in results and p not in failures:
                failures[p] = "응답에서 해당 페이지가 누락되었습니다."
        return results, {p: f for p, f in failures.items() if p not in results}

    def transcribe_pages_parallel(
        self,
        pages: List[Tuple[int, ImageOrLoader]],
        batch_size: int = 4,
        max_concurrent: int = 4,
        on_batch_done: Optional[Callable[[Dict[int, GeminiPageResult]], None]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
        cancelled_fn: Optional[Callable[[], bool]] = None,
    ) -> Tuple[Dict[int, GeminiPageResult], Dict[int, str]]:
        if not pages:
            return {}, {}

        bs = max(1, int(batch_size))
        batches = [pages[i:i + bs] for i in range(0, len(pages), bs)]
        all_results: Dict[int, GeminiPageResult] = {}
        all_failures: Dict[int, str] = {}

        ex = ThreadPoolExecutor(max_workers=max(1, int(max_concurrent)))
        try:
            pending = {
                ex.submit(self.transcribe_batch_resilient, b, cancelled_fn, log_cb)
                for b in batches
            }
            while pending:
                if cancelled_fn and cancelled_fn():
                    ex.shutdown(wait=False, cancel_futures=True)
                    raise InterruptedError("취소됨")
                done, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
                for fut in done:
                    res_map, fail_map = fut.result()
                    all_results.update(res_map)
                    all_failures.update(fail_map)
                    if on_batch_done and res_map:
                        on_batch_done(res_map)
        except BaseException:
            ex.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            ex.shutdown(wait=True)

        return all_results, all_failures