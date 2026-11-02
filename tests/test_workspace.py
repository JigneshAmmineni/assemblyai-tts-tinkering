"""Unit tests of LocalWorkspace. No network, no API key."""

from __future__ import annotations

from pathlib import Path

import pytest

from workspace import LocalWorkspace, WorkspaceError

NOTE = """# Project Atlas

Kickoff notes.

## Goals

- Ship the beta by March.
- Keep the API stable.

## Risks

Vendor lock-in.

### Mitigation

Abstract the storage layer.

## Open questions

None yet.
"""


@pytest.fixture
def ws(tmp_path: Path) -> LocalWorkspace:
    (tmp_path / "atlas.md").write_text(NOTE, encoding="utf-8")
    (tmp_path / "todo.txt").write_text("buy milk\ncall Sam\n", encoding="utf-8")
    (tmp_path / "meetings").mkdir()
    (tmp_path / "meetings" / "2026-11-01.md").write_text(
        "# Standup\n\nSam is out.\n", encoding="utf-8"
    )
    (tmp_path / "image.png").write_bytes(b"\x89PNG")
    (tmp_path / ".secret.md").write_text("hidden", encoding="utf-8")
    return LocalWorkspace(tmp_path)


def test_lists_only_notes_and_folders(ws: LocalWorkspace) -> None:
    names = [(e.path, e.is_dir) for e in ws.list()]
    assert names == [("meetings", True), ("atlas.md", False), ("todo.txt", False)]
    assert [e.path for e in ws.list("meetings")] == ["meetings/2026-11-01.md"]


def test_rejects_paths_outside_the_root(ws: LocalWorkspace, tmp_path: Path) -> None:
    (tmp_path.parent / "outside.md").write_text("x", encoding="utf-8")
    for bad in ["../outside.md", "/etc/passwd", "meetings/../../outside.md", ".secret.md"]:
        with pytest.raises(WorkspaceError):
            ws.read(bad)


def test_rejects_other_file_types(ws: LocalWorkspace) -> None:
    with pytest.raises(WorkspaceError, match="Only"):
        ws.read("image.png")
    with pytest.raises(WorkspaceError, match="Only"):
        ws.create("notes.docx", "x")


def test_search_finds_lines_and_names(ws: LocalWorkspace) -> None:
    hits = ws.search("sam")
    assert {(h.path, h.line) for h in hits} == {("meetings/2026-11-01.md", 3), ("todo.txt", 2)}


def test_read_whole_and_by_lines(ws: LocalWorkspace) -> None:
    whole = ws.read("atlas.md")
    assert whole.text == NOTE.rstrip("\n") and whole.start_line == 1 and whole.total_lines == 20
    part = ws.read("atlas.md", 5, 8)
    assert part.text == "## Goals\n\n- Ship the beta by March.\n- Keep the API stable."


def test_headings_and_sections(ws: LocalWorkspace) -> None:
    assert [(h.level, h.title) for h in ws.headings("atlas.md")] == [
        (1, "Project Atlas"),
        (2, "Goals"),
        (2, "Risks"),
        (3, "Mitigation"),
        (2, "Open questions"),
    ]
    risks = ws.section("atlas.md", "risks")
    assert (
        risks.text
        == "## Risks\n\nVendor lock-in.\n\n### Mitigation\n\nAbstract the storage layer.\n"
    )
    assert ws.section("atlas.md", "mitigation").text.startswith("### Mitigation")
    with pytest.raises(WorkspaceError, match="no heading"):
        ws.section("atlas.md", "budget")


def test_create_append_and_refuse_overwrite(ws: LocalWorkspace, tmp_path: Path) -> None:
    ws.create("ideas/new.md", "# Ideas\n\nFirst.")
    assert (tmp_path / "ideas" / "new.md").read_text(encoding="utf-8") == "# Ideas\n\nFirst.\n"
    with pytest.raises(WorkspaceError, match="already exists"):
        ws.create("ideas/new.md", "again")
    ws.append("ideas/new.md", "Second.")
    assert (tmp_path / "ideas" / "new.md").read_text(
        encoding="utf-8"
    ) == "# Ideas\n\nFirst.\n\nSecond.\n"


def test_replace_is_exact_and_unique(ws: LocalWorkspace, tmp_path: Path) -> None:
    assert ws.replace("atlas.md", "Ship the beta by March.", "Ship the beta by April.") == 1
    assert "by April." in (tmp_path / "atlas.md").read_text(encoding="utf-8")
    with pytest.raises(WorkspaceError, match="doesn't contain"):
        ws.replace("atlas.md", "by March.", "x")
    (tmp_path / "dup.md").write_text("same\nsame\n", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="2 times"):
        ws.replace("dup.md", "same", "other")


def test_insert_after_heading(ws: LocalWorkspace, tmp_path: Path) -> None:
    ws.insert_after_heading("atlas.md", "Goals", "- Write the docs.")
    text = (tmp_path / "atlas.md").read_text(encoding="utf-8")
    assert "- Keep the API stable.\n\n- Write the docs.\n\n## Risks" in text
    ws.insert_after_heading("atlas.md", "Open questions", "Who owns QA?")
    assert (
        (tmp_path / "atlas.md").read_text(encoding="utf-8").endswith("None yet.\n\nWho owns QA?\n")
    )
