"""`--dump TEXT --seg LINE`: the raw segments of ONE line, by FLEx's own number or the running
count (Seth, 2026-10-19: a Morphemes line showing every morph twice — the dump shows the bundles
exactly as the project returns them)."""
import pytest

from flex_scratchpad.__main__ import dump_range
from flex_scratchpad.flex.demo import DemoBackend, T_STORY
from flex_scratchpad.flex.lcm import FlexError


def test_the_lines_to_dump_by_count_and_by_flex_number():
    be = DemoBackend()
    assert dump_range(be, T_STORY, None) == (1, 3)
    assert dump_range(be, T_STORY, "4") == (4, 4)
    assert dump_range(be, T_STORY, "2-5") == (2, 5)
    segs = be.get_text(T_STORY, 1, 60)["segments"]
    by_label = {s["label"]: s["n"] for s in segs}
    a_label, b_label = segs[1]["label"], segs[3]["label"]
    assert dump_range(be, T_STORY, a_label) == (by_label[a_label], by_label[a_label])
    assert dump_range(be, T_STORY, f"{a_label}-{b_label}") == (by_label[a_label], by_label[b_label])
    with pytest.raises(FlexError):
        dump_range(be, T_STORY, "99.9")
