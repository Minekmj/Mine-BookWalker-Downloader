from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Callable, Dict, List, Optional, Tuple

from core.gemini.images import _make_labeled_png_bytes
from core.gemini.markup import (
    _is_json_parse_error,
    _is_rate_limit_error,
    _is_transient_gemini_error,
    _loads_json_relaxed,
)
from core.gemini.page_stats import compute_page_ink_ratio
from core.gemini.pool import GeminiKeyPool
from core.gemini.prompts import build_transcribe_system_prompt
from core.gemini.review import ReviewMixin
from core.gemini.schema import TRANSCRIBE_SCHEMA
from core.gemini.transcriber.models import GeminiPageResult, ImageOrLoader
from core.gemini.transcriber.parser import parse_page_paragraphs
from core.gemini.transcriber.split_helper import split_page_image_safe


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
        extra_prompts: Optional[Dict[str, str]] = None,
    ):
        self.pool = GeminiKeyPool(api_keys=api_keys, rpm_per_key=rpm_per_key)
        self.model_name = model_name.strip() or "gemini-3.1-flash-lite"
        self.temperature = max(0.0, min(1.5, float(temperature)))
        self.temp_step = max(0.0, float(temp_step))
        self.max_retries = max(1, int(max_retries))
        self.language = language.lower()
        self.orientation = orientation.lower()
        self.extra_prompts = dict(extra_prompts or {})

    def get_token_usage(self) -> Dict[str, int]:
        return self.pool.get_usage()

    def _build_transcribe_config(self, types_mod, temperature: float, model_to_use: str):
        safety = [
            types_mod.SafetySetting(category=cat, threshold=types_mod.HarmBlockThreshold.BLOCK_NONE)
            for cat in (
                types_mod.HarmCategory.HARM_CATEGORY_HARASSMENT,
                types_mod.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                types_mod.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                types_mod.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
            )
        ]
        kwargs = {
            "system_instruction": build_transcribe_system_prompt(self.language, self.orientation) + self._extra_prompt("prompt_extra_ocr"),
            "temperature": float(max(0.0, min(1.5, temperature))),
            "max_output_tokens": 32768,
            "response_mime_type": "application/json",
            "response_schema": TRANSCRIBE_SCHEMA,
            "safety_settings": safety,
        }
        model_l = (model_to_use or "").lower()
        if hasattr(types_mod, "ThinkingConfig"):
            try:
                if "gemini-3" in model_l:
                    kwargs["thinking_config"] = types_mod.ThinkingConfig(thinking_level="HIGH")
                elif "gemini-2.5" in model_l:
                    kwargs["thinking_config"] = types_mod.ThinkingConfig(thinking_budget=8192)
            except Exception:
                pass
        return types_mod.GenerateContentConfig(**kwargs)

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

        config = self._build_transcribe_config(types, temperature, model_to_use)
        resp = self.pool.generate(
            cancelled_fn=cancelled_fn,
            model=model_to_use,
            contents=contents,
            config=config,
        )

        raw_text = (getattr(resp, "text", None) or "").strip()
        if not raw_text:
            raise ValueError("Gemini 응답이 비어 있습니다 (안전 필터 또는 빈 출력).")

        data = _loads_json_relaxed(raw_text)
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
            raw_paras = p_item.get("paragraphs", [])
            para_objs = parse_page_paragraphs(raw_paras, ends_open, p_no, self.language)
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
        split_depth: int = 0,
    ) -> Tuple[Dict[int, GeminiPageResult], Dict[int, str]]:
        results: Dict[int, GeminiPageResult] = {}
        failures: Dict[int, str] = {}
        pending = list(batch)
        base_temp = self.temperature if start_temp is None else float(start_temp)
        attempts = max(1, int(max_attempts if max_attempts is not None else self.max_retries))

        for attempt in range(1, attempts + 1):
            if not pending or (cancelled_fn and cancelled_fn()):
                break
            step = self.temp_step if self.temp_step > 0 else 0.2
            cur_temp = round(max(0.0, min(1.5, base_temp + step * (attempt - 1))), 4)
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
                    log_cb(f"누락 페이지 {[p for p, _ in pending]} 누적 재시도 ({attempt}/{attempts}, temp={cur_temp})")
            except InterruptedError:
                raise
            except Exception as exc:
                err_str = str(exc) or type(exc).__name__
                for p, _ in pending:
                    failures[p] = err_str
                if log_cb:
                    log_cb(f"요청 오류 {[p for p, _ in pending]} (시도 {attempt}/{attempts}, temp={cur_temp}): {err_str}")
                if len(pending) > 1 and (_is_json_parse_error(exc) or (not _is_transient_gemini_error(exc) and attempt >= 2)):
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
                if len(pending) == 1 and split_depth < 3 and (_is_json_parse_error(exc) or (not _is_transient_gemini_error(exc) and attempt >= 2)):
                    p_no, img_or_fn = pending[0]
                    raw_img = img_or_fn() if callable(img_or_fn) else img_or_fn
                    halves = split_page_image_safe(raw_img, vertical_text=(self.orientation == "vertical"))
                    if halves is not None:
                        first_img, second_img = halves
                        if log_cb:
                            log_cb(f"p{p_no} JSON/반복 오류로 여백 기준 반분할 재시도 (깊이 {split_depth + 1})")
                        res1, fail1 = self.transcribe_batch_resilient(
                            [(p_no, first_img)], cancelled_fn, log_cb, start_temp=cur_temp, model_override=model_override, max_attempts=2, split_depth=split_depth + 1
                        )
                        res2, fail2 = self.transcribe_batch_resilient(
                            [(p_no, second_img)], cancelled_fn, log_cb, start_temp=cur_temp, model_override=model_override, max_attempts=2, split_depth=split_depth + 1
                        )
                        if p_no in res1 and p_no in res2:
                            combined_paras = list(res1[p_no].paragraphs) + list(res2[p_no].paragraphs)
                            for r_idx, para_obj in enumerate(combined_paras):
                                para_obj.reading_order = r_idx
                            return {
                                p_no: GeminiPageResult(
                                    page_no=p_no,
                                    paragraphs=combined_paras,
                                    used_temp=res2[p_no].used_temp,
                                    used_model=res2[p_no].used_model,
                                    ink_ratio=compute_page_ink_ratio(raw_img),
                                )
                            }, {}
                        err_msg = fail1.get(p_no) or fail2.get(p_no) or err_str
                        return {}, {p_no: err_msg}
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
            pending = {ex.submit(self.transcribe_batch_resilient, b, cancelled_fn, log_cb) for b in batches}
            while pending:
                if cancelled_fn and cancelled_fn():
                    for fut in list(pending):
                        if fut.done() and not fut.cancelled():
                            try:
                                res_map, fail_map = fut.result()
                                all_results.update(res_map)
                                all_failures.update(fail_map)
                                if on_batch_done and res_map:
                                    on_batch_done(res_map)
                            except Exception:
                                pass
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
