"""Bounded-cardinality Prometheus metrics for the private STT worker."""

from __future__ import annotations

import threading
import time
from collections import Counter
from contextlib import contextmanager


_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)


class STTMetrics:
    def __init__(self):
        self._lock = threading.Lock()
        self._requests = Counter()
        self._durations = Counter()
        self._inflight = 0

    @contextmanager
    def request(self):
        started = time.monotonic()
        outcome = ["success"]
        with self._lock:
            self._inflight += 1
        try:
            yield lambda value: outcome.__setitem__(0, self._allowed_outcome(value))
        finally:
            elapsed = time.monotonic() - started
            with self._lock:
                self._inflight -= 1
                self._requests[outcome[0]] += 1
                self._durations["count"] += 1
                self._durations["sum"] += elapsed
                for bucket in _BUCKETS:
                    if elapsed <= bucket:
                        self._durations[bucket] += 1

    @staticmethod
    def _allowed_outcome(value):
        allowed = {
            "success",
            "invalid_input",
            "overloaded",
            "not_ready",
            "timeout",
            "backend_error",
            "decode_error",
        }
        return value if value in allowed else "backend_error"

    def render(self, ready):
        with self._lock:
            requests = dict(self._requests)
            durations = dict(self._durations)
            inflight = self._inflight
        lines = [
            "# HELP speech_stt_requests_total Completed STT requests by outcome.",
            "# TYPE speech_stt_requests_total counter",
        ]
        for outcome in (
            "success",
            "invalid_input",
            "overloaded",
            "not_ready",
            "timeout",
            "backend_error",
            "decode_error",
        ):
            lines.append(
                f'speech_stt_requests_total{{outcome="{outcome}"}} {requests.get(outcome, 0)}'
            )
        lines.extend(
            (
                "# HELP speech_stt_request_duration_seconds Request duration.",
                "# TYPE speech_stt_request_duration_seconds histogram",
            )
        )
        for bucket in _BUCKETS:
            lines.append(
                f'speech_stt_request_duration_seconds_bucket{{le="{bucket:g}"}} {durations.get(bucket, 0)}'
            )
        lines.extend(
            (
                f'speech_stt_request_duration_seconds_bucket{{le="+Inf"}} {durations.get("count", 0)}',
                f"speech_stt_request_duration_seconds_sum {durations.get('sum', 0):.6f}",
                f"speech_stt_request_duration_seconds_count {durations.get('count', 0)}",
                "# HELP speech_stt_inflight_requests Active HTTP STT requests.",
                "# TYPE speech_stt_inflight_requests gauge",
                f"speech_stt_inflight_requests {inflight}",
                "# HELP speech_ready Whether this component can serve inference.",
                "# TYPE speech_ready gauge",
                f"speech_ready {1 if ready else 0}",
            )
        )
        return "\n".join(lines) + "\n"
