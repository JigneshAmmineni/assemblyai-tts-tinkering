"""Text-only tests of the assistant, through the LLM Gateway.

Each test sends the agent one line, as text, and checks what it does: which tools it calls,
what changed on disk, and what it says, judged by an LLM. The tests need ASSEMBLYAI_API_KEY
(from .env.local or the environment) and no audio.

    uv run pytest
"""

from __future__ import annotations

import os
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from livekit.agents import AgentSession, llm
from livekit.agents.voice.run_result import ChatMessageEvent, FunctionCallEvent, RunResult

from agent import _ACK, Assistant, CallState, llm_gateway
from workspace import LocalWorkspace

pytestmark = pytest.mark.skipif(
    not os.getenv("ASSEMBLYAI_API_KEY"), reason="needs ASSEMBLYAI_API_KEY for the LLM Gateway"
)

# The judge doesn't need to be fast. claude-sonnet-4-6 once the account can use it; until then
# the same model at default effort.
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "gemma-4-31b")

SAMPLE = Path(__file__).parents[1] / "sample-workspace"


@pytest.fixture
def notes(tmp_path: Path) -> Path:
    shutil.copytree(SAMPLE, tmp_path / "notes")
    return tmp_path / "notes"


@pytest.fixture
async def session(notes: Path) -> AsyncIterator[AgentSession]:
    workspace = LocalWorkspace(notes)
    async with (
        llm_gateway() as agent_llm,
        AgentSession[CallState](llm=agent_llm, userdata=CallState(workspace=workspace)) as session,
    ):
        await session.start(Assistant(workspace))
        yield session


@pytest.fixture
async def judge() -> AsyncIterator[llm.LLM]:
    async with llm_gateway(JUDGE_MODEL, reasoning_effort=None) as judge:
        yield judge


def called(result: RunResult, *names: str) -> set[str]:
    """Which of the named tools the agent called."""
    return {
        e.item.name
        for e in result.events
        if isinstance(e, FunctionCallEvent) and e.item.name in names
    }


def spoken(result: RunResult) -> list[str]:
    """What the agent said, after dropping the bare acknowledgments the TTS filter drops."""
    texts = [
        (e.item.text_content or "").strip()
        for e in result.events
        if isinstance(e, ChatMessageEvent) and e.item.role == "assistant"
    ]
    return [t for t in texts if t and not _ACK.match(t)]


async def test_recites_a_section_verbatim(session: AgentSession, judge: llm.LLM) -> None:
    result = await session.run(
        user_input="Read me the action items from the October 28 Atlas standup, word for word."
    )

    assert called(result, "read_section", "read_note"), "didn't read the note"
    await (
        result.expect[-1]
        .is_message(role="assistant")
        .judge(
            judge,
            intent=(
                "Recites both action items essentially verbatim: Priya asks legal about the "
                "analytics vendor renewal, and Sam writes the runbook for the billing integration. "
                "No commentary before or after beyond at most a word or two."
            ),
        )
    )


async def test_answers_a_question_briefly(session: AgentSession, judge: llm.LLM) -> None:
    result = await session.run(user_input="Who is on the Atlas team?")

    assert called(result, "read_note", "read_section", "search_notes"), "didn't look at the notes"
    await (
        result.expect[-1]
        .is_message(role="assistant")
        .judge(
            judge,
            intent=(
                "Names Priya Nair, Sam Okafor, Lena Fischer and Diego Alvarez (roles optional) "
                "in a short spoken reply, with no preamble, no markdown and no closing remark."
            ),
        )
    )


async def test_stays_silent_after_a_successful_append(session: AgentSession, notes: Path) -> None:
    result = await session.run(user_input="Add 'Buy printer paper' to the todo list.")

    result.expect.contains_function_call(name="append_to_note")
    assert "Buy printer paper" in (notes / "todo.txt").read_text(encoding="utf-8")
    assert spoken(result) == [], f"agent spoke after a clean success: {spoken(result)}"


async def test_creates_a_dictated_note(session: AgentSession, notes: Path) -> None:
    result = await session.run(
        user_input=(
            "Create a new note called ideas. The content is: Try a weekly office hours slot "
            "for design partners."
        )
    )

    result.expect.contains_function_call(name="create_note")
    created = list(notes.rglob("ideas*"))
    assert created, "no ideas note was created"
    assert "weekly office hours" in created[0].read_text(encoding="utf-8")
    assert spoken(result) == [], f"agent spoke after a clean success: {spoken(result)}"


async def test_makes_an_exact_edit(session: AgentSession, notes: Path) -> None:
    result = await session.run(
        user_input=("In the Atlas note, change the beta date from March 15 to March 22.")
    )

    result.expect.contains_function_call(name="replace_in_note")
    text = (notes / "project-atlas.md").read_text(encoding="utf-8")
    assert "March 22" in text and "March 15" not in text


async def test_asks_which_note_when_ambiguous(session: AgentSession, judge: llm.LLM) -> None:
    result = await session.run(user_input="Add a line that says call Priya.")

    assert not any(
        isinstance(e, ChatMessageEvent) and e.item.role == "assistant" and not e.item.text_content
        for e in result.events
    )
    await (
        result.expect[-1]
        .is_message(role="assistant")
        .judge(judge, intent="Asks which note to add it to, in one short sentence.")
    )


async def test_hangs_up_after_goodbye(session: AgentSession) -> None:
    result = await session.run(user_input="That's everything, thanks. Bye!")

    result.expect.contains_function_call(name="end_call")
