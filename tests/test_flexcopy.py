"""The plain-text copies of FLEx objects that a note's file carries so it reads without the app
(ui/js/flexcopy.js writes them; Seth, 2026-10-17). Python leaves them out wherever the app's own
view of a note is meant: excerpts, search and #tags. The fixture is written by
tests/js/flexcopy.test.js from the page's own code, so the two stay in step."""
from pathlib import Path

from flex_scratchpad.api import Api
from flex_scratchpad.config import AppConfig
from flex_scratchpad.notebook import excerpt, inline_tags, without_flex_copies

FIX = Path(__file__).parent / "fixtures"


def test_python_strips_the_copies_the_page_writes():
    written = (FIX / "flexcopy-note.md").read_text(encoding="utf-8")
    assert "flex-copy" in written
    assert without_flex_copies(written) == (FIX / "flexcopy-note.stripped.md").read_text(encoding="utf-8")


def test_excerpts_search_and_tags_do_not_see_the_copies(tmp_path):
    body = ('Notes on #verbs {{flex:text 9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b0001 seg=1}}'
            '[The dog and the river 1.1: ‘The #dog slept.’](silfw://localhost/link?guid=x "flex-copy") end\n\n'
            '{{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}}\n'
            '[kabir (n)](silfw://localhost/link?guid=y "flex-copy")\n'
            '```flex-copy\n1. n ‘zebrafish’\n```\n')
    assert inline_tags(body) == ["verbs"]
    assert "river" not in excerpt(body) and "zebrafish" not in excerpt(body)
    api = Api(AppConfig(tmp_path / "config.json"), notebook_dir=tmp_path / "nb", demo=True)
    n = api.create_note(None, "", "Copies", body)
    assert not [h for h in api.search("zebrafish") if h["id"] == n["id"]]
    assert [h for h in api.search("verbs") if h["id"] == n["id"]]
    # the file keeps them, and the Markdown export (what a reader without the app gets) too
    out = tmp_path / "copies.md"
    api.export_note_markdown(n["id"], str(out))
    assert "```flex-copy" in out.read_text(encoding="utf-8")
