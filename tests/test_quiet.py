"""The acknowledgment filter in front of the TTS. No network, no API key."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from agent import _drop_acknowledgments, keyterms
from workspace import LocalWorkspace


async def chunks(*parts: str) -> AsyncIterator[str]:
    for p in parts:
        yield p


async def collect(parts: tuple[str, ...]) -> str:
    return "".join([c async for c in _drop_acknowledgments(chunks(*parts))])


@pytest.mark.parametrize(
    "reply",
    [
        ("Done.",),
        ("Do", "ne"),
        ("Okay",),
        ("Got it!",),
        ("Added.",),
        ("empty",),
        ("(silence)",),
        ("激",),
        ("…",),
    ],
)
async def test_drops_bare_acknowledgments(reply: tuple[str, ...]) -> None:
    assert await collect(reply) == ""


@pytest.mark.parametrize(
    "reply",
    [
        ("Done, but the note already had that line.",),
        ("Which note?",),
        ("Priya Nair leads product. ", "Sam Okafor is on backend."),
        (
            "The ",
            "todo list ",
            "has four items.",
        ),
    ],
)
async def test_keeps_everything_else(reply: tuple[str, ...]) -> None:
    assert await collect(reply) == "".join(reply)


def test_keyterms_come_from_note_names(tmp_path) -> None:
    (tmp_path / "project-atlas.md").write_text("x", encoding="utf-8")
    (tmp_path / "2026-10-28-standup.md").write_text("x", encoding="utf-8")
    terms = keyterms(LocalWorkspace(tmp_path))
    assert {"Project", "Atlas", "Standup"} <= set(terms)
    assert "2026" not in terms
