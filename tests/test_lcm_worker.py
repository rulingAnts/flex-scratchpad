"""The single LCM worker thread: a job that calls back into the worker (one backend method using
another, as explain_doubled_bundles uses list_texts) runs inline instead of queueing behind
itself — queued, it waited for a thread that was waiting for it (Seth, 2026-10-19: a scan sat at
0 % CPU for minutes until the 600 s timeout)."""
import threading

from flex_scratchpad.flex.lcm import LcmWorker


def test_a_nested_call_from_the_worker_runs_inline_instead_of_deadlocking():
    w = LcmWorker()
    try:
        seen = {}

        def inner():
            seen["inner_thread"] = threading.current_thread().name
            return 7

        def outer():
            seen["outer_thread"] = threading.current_thread().name
            return w.call(inner, timeout=2) + 1

        assert w.call(outer, timeout=5) == 8
        assert seen == {"outer_thread": "lcm-worker", "inner_thread": "lcm-worker"}
        assert w.call(lambda: threading.current_thread().name, timeout=2) == "lcm-worker"   # an ordinary call still queues
    finally:
        w.stop()
