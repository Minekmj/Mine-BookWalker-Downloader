import re
import time
from typing import Callable, Optional

from core.gemini.markup import _is_json_parse_error, _is_rate_limit_error, _loads_json_relaxed

_HANGUL_RE = re.compile(r"[\uAC00-\uD7A3\u1100-\u11FF\u3130-\u318F]")


def is_retryable_review_error(exc: Exception) -> bool:
    if _is_json_parse_error(exc):
        return True
    s = str(exc).lower()
    tokens = (
        "503", "unavailable", "high demand", "overloaded",
        "500", "502", "504", "internal",
        "429", "resource_exhausted", "rate limit", "quota", "too many requests",
        "timeout", "timed out", "connection", "reset", "temporarily",
        "empty", "비어", "expecting value", "unterminated", "json",
    )
    return any(tok in s for tok in tokens)


class ReviewBaseMixin:
    def _extra_prompt(self, key: str) -> str:
        val = str((getattr(self, "extra_prompts", None) or {}).get(key, "") or "").strip()
        return f"\n[사용자 추가 요청사항]\n{val}\n" if val else ""

    def _make_config(self, types_mod, temperature: float, max_output_tokens: int, schema: dict, thinking_level: str = "HIGH"):
        kwargs = {
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
            "response_mime_type": "application/json",
            "response_schema": schema,
        }
        model_l = (self.model_name or "").lower()
        lvl = thinking_level.upper()
        if hasattr(types_mod, "ThinkingConfig"):
            try:
                if "gemini-3" in model_l:
                    kwargs["thinking_config"] = types_mod.ThinkingConfig(thinking_level=lvl)
                elif "gemini-2.5" in model_l:
                    budget = 8192 if lvl == "HIGH" else 2048
                    kwargs["thinking_config"] = types_mod.ThinkingConfig(thinking_budget=budget)
            except Exception:
                pass
        return types_mod.GenerateContentConfig(**kwargs)

    def _sleep_cancelable(self, seconds: float, cancelled_fn: Optional[Callable[[], bool]] = None):
        deadline = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < deadline:
            if cancelled_fn and cancelled_fn():
                raise InterruptedError("취소됨")
            time.sleep(min(0.25, max(0.01, deadline - time.monotonic())))

    def _generate_json_with_retry(
        self,
        contents,
        config,
        cancelled_fn: Optional[Callable[[], bool]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
        label: str = "검수",
        max_attempts: Optional[int] = None,
        fast_fail_on_json_error: bool = False,
    ):
        attempts = max(1, int(max_attempts if max_attempts is not None else self.max_retries))
        last_exc: Optional[Exception] = None
        cur_config = config
        for attempt in range(1, attempts + 1):
            if cancelled_fn and cancelled_fn():
                raise InterruptedError("취소됨")
            try:
                response = self.pool.generate(
                    cancelled_fn=cancelled_fn,
                    model=self.model_name,
                    contents=contents,
                    config=cur_config,
                )
                raw = (getattr(response, "text", None) or "").strip()
                if not raw:
                    raise ValueError("Gemini 검수 응답이 비어 있습니다.")
                return _loads_json_relaxed(raw)
            except InterruptedError:
                raise
            except Exception as exc:
                last_exc = exc
                if fast_fail_on_json_error and _is_json_parse_error(exc):
                    raise
                if attempt >= attempts or not is_retryable_review_error(exc):
                    raise
                if _is_json_parse_error(exc) and hasattr(cur_config, "model_copy"):
                    cur_t = float(getattr(cur_config, "temperature", 0.0) or 0.0)
                    cur_config = cur_config.model_copy(update={"temperature": min(0.8, round(cur_t + 0.25, 2))})
                if _is_rate_limit_error(exc):
                    if log_cb:
                        log_cb(f"[{label}] 할당량 대기 후 재시도 ({attempt}/{attempts})")
                elif log_cb:
                    log_cb(f"[{label}] 일시 오류로 재시도 ({attempt}/{attempts}): {exc}")
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("검수 요청 실패")
