from collections import deque
from dataclasses import dataclass
import re
import threading
import time
from typing import Callable, Dict, List, Optional

from core.gemini.markup import _is_rate_limit_error

RETRY_DELAY_RE = re.compile(
    r"retry(?:ing)?\s+in\s+([0-9]+(?:\.[0-9]+)?)s|retryDelay['\"]?\s*:\s*['\"]([0-9]+(?:\.[0-9]+)?)s",
    re.IGNORECASE,
)


def _parse_retry_delay_sec(exc: Exception) -> float:
    m = RETRY_DELAY_RE.search(str(exc))
    if not m:
        return 45.0
    raw = m.group(1) or m.group(2)
    try:
        return max(40.0, min(70.0, float(raw) + 2.0))
    except (TypeError, ValueError):
        return 45.0


@dataclass
class _KeySlot:
    index: int
    api_key: str
    client: object
    timestamps: deque
    cooldown_until: float = 0.0
    in_flight: int = 0


class GeminiKeyPool:

    def __init__(self, api_keys: List[str], rpm_per_key: int):
        if not api_keys:
            raise ValueError("Gemini API 키가 최소 1개 이상 필요합니다.")
        from google import genai
        from google.genai import types

        self.rpm = max(1, int(rpm_per_key))
        self._cond = threading.Condition()
        self._usage_lock = threading.Lock()
        self._input_tokens = 0
        self._output_tokens = 0
        self._total_tokens = 0
        self._requests = 0
        try:
            http_opts = types.HttpOptions(timeout=90000)
            self._slots = [
                _KeySlot(index=i, api_key=k, client=genai.Client(api_key=k, http_options=http_opts), timestamps=deque())
                for i, k in enumerate(api_keys)
            ]
        except Exception:
            self._slots = [
                _KeySlot(index=i, api_key=k, client=genai.Client(api_key=k), timestamps=deque())
                for i, k in enumerate(api_keys)
            ]

    def slot_count(self) -> int:
        return len(self._slots)

    def get_usage(self) -> Dict[str, int]:
        with self._usage_lock:
            return {
                "input_tokens": self._input_tokens,
                "output_tokens": self._output_tokens,
                "total_tokens": self._total_tokens,
                "requests": self._requests,
            }

    def acquire(self, cancelled_fn: Optional[Callable[[], bool]] = None) -> _KeySlot:
        with self._cond:
            while True:
                if cancelled_fn and cancelled_fn():
                    raise InterruptedError("취소됨")

                now = time.monotonic()
                best_slot: Optional[_KeySlot] = None
                min_wait = 60.0

                for slot in self._slots:
                    while slot.timestamps and (now - slot.timestamps[0]) >= 60.0:
                        slot.timestamps.popleft()

                    if slot.cooldown_until > now:
                        min_wait = min(min_wait, slot.cooldown_until - now)
                        continue

                    if len(slot.timestamps) < self.rpm:
                        if best_slot is None or (slot.in_flight, len(slot.timestamps)) < (
                            best_slot.in_flight,
                            len(best_slot.timestamps),
                        ):
                            best_slot = slot
                    else:
                        wait_sec = 60.05 - (now - slot.timestamps[0])
                        min_wait = min(min_wait, max(0.05, wait_sec))

                if best_slot is not None:
                    best_slot.timestamps.append(now)
                    best_slot.in_flight += 1
                    return best_slot

                self._cond.wait(timeout=min(1.0, max(0.05, min_wait)))

    def release(self, slot: _KeySlot, cooldown_sec: float = 0.0):
        with self._cond:
            slot.in_flight = max(0, slot.in_flight - 1)
            if cooldown_sec > 0:
                slot.cooldown_until = max(slot.cooldown_until, time.monotonic() + cooldown_sec)
            self._cond.notify_all()

    def generate(self, cancelled_fn: Optional[Callable[[], bool]] = None, **kwargs):
        slot = self.acquire(cancelled_fn=cancelled_fn)
        cooldown = 0.0
        try:
            resp = slot.client.models.generate_content(**kwargs)
            usage = getattr(resp, "usage_metadata", None)
            if usage is not None:
                in_tok = int(getattr(usage, "prompt_token_count", 0) or 0)
                cand_tok = int(getattr(usage, "candidates_token_count", 0) or 0)
                thought_tok = int(getattr(usage, "thoughts_token_count", 0) or 0)
                out_tok = cand_tok + thought_tok
                tot_tok = int(getattr(usage, "total_token_count", 0) or (in_tok + out_tok))
                with self._usage_lock:
                    self._input_tokens += in_tok
                    self._output_tokens += out_tok
                    self._total_tokens += tot_tok
                    self._requests += 1
            else:
                with self._usage_lock:
                    self._requests += 1
            return resp
        except Exception as exc:
            if _is_rate_limit_error(exc):
                cooldown = _parse_retry_delay_sec(exc)
            raise
        finally:
            self.release(slot, cooldown_sec=cooldown)