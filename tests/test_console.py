"""The CLI's messages carry "→", "…" and "—"; a Windows console in cp1252 cannot encode them and
Python raises UnicodeEncodeError on print — the VM's run of --doubled-morphs died on the final arrow
after the summary (2026-10-20). `console_safe` makes such a stream replace what it cannot encode."""
import io

from flex_scratchpad.__main__ import console_safe


def test_an_unencodable_character_is_replaced_instead_of_ending_the_command():
    raw = io.BytesIO()
    out = io.TextIOWrapper(raw, encoding="cp1252", errors="strict", write_through=True)
    try:
        print("→ report.json", file=out)
    except UnicodeEncodeError:
        pass
    else:
        raise AssertionError("cp1252 should not encode the arrow")
    console_safe(out)
    print("→ report.json ✓", file=out)                 # neither character exists in cp1252
    assert raw.getvalue().rstrip(b"\r\n") == b"? report.json ?"


def test_main_makes_the_console_safe_first():
    from pathlib import Path
    import flex_scratchpad.__main__ as m
    src = Path(m.__file__).read_text(encoding="utf-8")
    body = src.split("def main(")[1]
    assert body.lstrip().startswith("argv: list[str] | None = None) -> int:\n    console_safe()")
