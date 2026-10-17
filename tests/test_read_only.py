"""FLEx Scratchpad never writes to a FLEx project (Seth, 2026-10-17: "Read-only is good for this
project", and the site tells users so). This fails the build if the code gains a way to: a project
opened for writing, a unit of work or undo task (how LCM changes data), a save. The program's own
files — the notebook, its cache, the exports a user saves — are not a FLEx project and not checked
here."""
import re
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "flex_scratchpad"
WRITES = re.compile(r"writeEnabled\s*=\s*True|UnitOfWork|UndoableTask|BeginUndoTask|ActionHandler"
                    r"|SaveProject|SaveChanges|\.Save\(|CmMediaURI")


def sources():
    return [p for p in PKG.rglob("*.py") if "__pycache__" not in p.parts]


def test_nothing_in_the_program_can_write_to_a_flex_project():
    hits = [f"{p.relative_to(PKG)}:{n}: {line.strip()}"
            for p in sources()
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if WRITES.search(line)]
    assert hits == [], "FLEx Scratchpad is read-only; these lines could write to a FLEx project:\n" + "\n".join(hits)


def test_the_project_is_opened_read_only_and_only_there():
    lcm = (PKG / "flex" / "lcm.py").read_text(encoding="utf-8")
    opens = re.findall(r"OpenProject\(([^)]*)\)", lcm)
    assert opens == ["name, writeEnabled=False"], opens
    others = [p.relative_to(PKG) for p in sources() if p.name != "lcm.py" and "OpenProject(" in p.read_text(encoding="utf-8")]
    assert others == []
