import json
import logging

from thicket.api.middleware import TokenBucketLimiter
from thicket.logging_setup import JsonFormatter


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_token_bucket_per_key_and_refill():
    clock = Clock()
    lim = TokenBucketLimiter(3, clock=clock)
    assert [lim.allow("a")[0] for _ in range(4)] == [True, True, True, False]
    allowed, wait = lim.allow("a")
    assert not allowed and 0 < wait <= 20
    assert lim.allow("b")[0]  # separate bucket
    clock.t += 20.0  # one token per 20 s at 3/min
    assert lim.allow("a")[0]
    assert not lim.allow("a")[0]


def test_token_bucket_disabled():
    lim = TokenBucketLimiter(0)
    assert all(lim.allow("x")[0] for _ in range(100))


def test_json_formatter_includes_extra_fields():
    rec = logging.LogRecord(
        "thicket.test", logging.INFO, __file__, 1, "analysis completed", (), None
    )
    rec.analysis_id = "ana_1"
    rec.stage_timings_ms = {"model:birdnet": 12}
    out = json.loads(JsonFormatter().format(rec))
    assert out["msg"] == "analysis completed"
    assert out["analysis_id"] == "ana_1"
    assert out["stage_timings_ms"] == {"model:birdnet": 12}
    assert out["level"] == "INFO" and "ts" in out
