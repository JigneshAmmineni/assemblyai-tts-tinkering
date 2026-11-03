"""A voice assistant for a folder of notes, where every model is AssemblyAI's.

- Speech-to-text: Universal-3.6 Pro streaming, which also decides when the user has finished
- LLM: a model on the LLM Gateway (Claude Sonnet 5.5 once the account can use it), thinking on
  at low effort
- Text-to-speech: AssemblyAI streaming TTS, with word-level timings

The agent reads, searches, recites, creates and edits the Markdown and text files under
WORKSPACE_ROOT, and says as little as possible while doing it.

    uv run src/agent.py console   # talk to the agent in your terminal
    uv run src/agent.py dev       # connect it to LiveKit Cloud, for a web or phone frontend
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    ModelSettings,
    RunContext,
    ToolError,
    ToolResult,
    TurnHandlingOptions,
    cli,
    function_tool,
)
from livekit.agents.beta.tools import EndCallTool
from livekit.plugins import assemblyai, openai, silero

from workspace import LocalWorkspace, Workspace, WorkspaceError

load_dotenv(Path(__file__).parents[1] / ".env.local")

logger = logging.getLogger("agent")

# Frontends, phone numbers and the Agent Console ask LiveKit for the agent by this name
AGENT_NAME = os.getenv("AGENT_NAME", "assistant")

# --- Settings, all overridable from the environment ---

# The folder of notes the agent works in. In the container this is /workspace, a mounted volume.
WORKSPACE_ROOT = os.getenv("WORKSPACE_ROOT") or str(Path(__file__).parents[1] / "sample-workspace")

# A voice id from https://www.assemblyai.com/dashboard/text-to-speech/voices, or a cloned voice's id
TTS_VOICE = os.getenv("TTS_VOICE_ID", "49c443a4-8a1d-5f7e-b70b-98bdbd9823c3")  # Audrey
ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "Audrey")

# Turn detection: "min_latency", "balanced" or "max_accuracy"
STT_MODE = "balanced"
# How loud speech must be to count, for transcription and for interrupting the agent
VAD_THRESHOLD = 0.2

# The intended model is claude-sonnet-5-5. On 2026-11-01 this account's Gateway tier only
# served AssemblyAI-hosted models (gemma-4-31b, qwen3.5-4b-32k-fast); third-party models
# answered "Your account does not have access to this LLM Gateway model". Set LLM_MODEL once
# the account can use Claude.
LLM_MODEL = os.getenv("LLM_MODEL", "gemma-4-31b")
# Thinking stays on; "low" keeps the wait before the first word short
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "low")
LLM_GATEWAY_URL = os.getenv("LLM_GATEWAY_URL", "https://llm-gateway.assemblyai.com/v1")

GREETING = "Ready."

INSTRUCTIONS = """\
You are {name}, a voice assistant that works inside a folder of notes: Markdown and text files. \
You are talking with someone live, and everything you write is spoken aloud.

What you do: list, search, read and summarize notes; recite passages word for word; create \
notes; append to them; and make exact edits the user dictates. Use the tools for all of it. \
Never invent file names or contents: look first.

How to behave, in order of importance:

1. Silence is the default. When a task succeeds with nothing unexpected, end your turn \
without writing any words. Don't write "done", "okay", "empty" or a placeholder, don't \
summarize what you did, and don't offer more help. The user will ask if they want to know.
2. Speak only when the user needs something from you: a tool failed, a name was ambiguous, \
you need a decision, something unexpected turned up, or they asked a question. Never pick a \
note the user didn't name: if no note is open and they didn't say which, ask which one in a \
few words instead of guessing.
3. When you do speak, be brief: short separate statements, one fact each, like spoken bullet \
points. No preamble, no restating what the user said, no praise, no closing remark. Don't \
try to have the last word.
4. Explain, elaborate or give detail only when asked.
5. When asked to read or recite something, speak the text exactly as written. Do not \
paraphrase, summarize or skip anything, and don't add commentary before or after.
6. When the user dictates text to insert or replace, write their words verbatim, with sensible \
punctuation and capitalization. Don't rephrase or improve it. If the exact passage to \
replace isn't clear, read the candidate back and ask.
7. For broad instructions ("tidy the action items", "add what we decided today"), do the work \
with the tools, then stay silent unless you had to make a judgment call the user would want \
to know about. Then say what you decided in one short statement.
8. Markdown symbols, file extensions and paths sound bad aloud. Say "the Atlas note", not \
"project hyphen atlas dot md". Say a heading's words, not its hash marks.
9. If you didn't catch something, say so briefly and ask again rather than guess.

Only state facts from the notes and the tools. When the person says goodbye, call end_call \
without saying anything."""


@dataclass
class CallState:
    workspace: Workspace
    current_note: str | None = None  # the last note read or written, for "add to it"


# Replies that carry no information: bare acknowledgments, and the placeholders a model writes
# when told to say nothing. They are dropped before reaching the TTS.
_ACK = re.compile(
    r"^[(\[]?(done|ok|okay|sure|got it|all set|will do|alright|no problem|added|saved|updated|"
    r"created|noted|understood|on it|done and done|empty|silence|silent|no response|nothing|"
    r"no reply)[)\]]?[.!]?$",
    re.IGNORECASE,
)
_ACK_MAX_CHARS = 24


class Assistant(Agent):
    def __init__(self, workspace: Workspace) -> None:
        super().__init__(
            instructions=INSTRUCTIONS.format(name=ASSISTANT_NAME),
            tools=[EndCallTool(ignore_on_enter=True)],
        )
        self._workspace = workspace

    async def on_enter(self) -> None:
        self.session.say(GREETING)

    # -- quiet by default ----------------------------------------------------------------------

    async def tts_node(
        self, text: AsyncIterable[str], model_settings: ModelSettings
    ) -> AsyncIterable:
        return Agent.default.tts_node(self, _drop_acknowledgments(text), model_settings)

    # -- helpers -------------------------------------------------------------------------------

    def _note(self, context: RunContext[CallState], path: str | None) -> str:
        if path:
            context.userdata.current_note = path
            return path
        if context.userdata.current_note:
            return context.userdata.current_note
        raise ToolError("No note is open. Ask which note the user means.")

    # -- reading tools -------------------------------------------------------------------------

    @function_tool
    async def list_notes(self, context: RunContext[CallState], folder: str = "") -> str:
        """List the notes and folders in the workspace, or in one folder of it.

        Args:
            folder: A folder path inside the workspace, or empty for the top level
        """
        try:
            entries = self._workspace.list(folder)
        except WorkspaceError as e:
            raise ToolError(str(e)) from None
        if not entries:
            return "The folder is empty."
        names = [f"{e.path} (folder)" if e.is_dir else e.path for e in entries]
        return "Contents: " + "; ".join(names)

    @function_tool
    async def search_notes(self, context: RunContext[CallState], query: str) -> str:
        """Find notes that mention a word or phrase, by file name or by content.

        Args:
            query: The word or phrase to look for, case-insensitive
        """
        try:
            hits = self._workspace.search(query)
        except WorkspaceError as e:
            raise ToolError(str(e)) from None
        if not hits:
            return f"Nothing mentions '{query}'."
        lines = [
            f"{h.path} line {h.line}: {h.text}" if h.line else f"{h.path} (file name)" for h in hits
        ]
        return "Matches:\n" + "\n".join(lines)

    @function_tool
    async def outline_note(self, context: RunContext[CallState], path: str | None = None) -> str:
        """Get the headings of a note, with their line numbers, to find a section.

        Args:
            path: The note's path. Omit to use the note currently open.
        """
        note = self._note(context, path)
        try:
            heads = self._workspace.headings(note)
            total = self._workspace.read(note).total_lines
        except WorkspaceError as e:
            raise ToolError(str(e)) from None
        if not heads:
            return f"{note} has {total} lines and no headings."
        return f"{note} has {total} lines. Headings: " + "; ".join(
            f"{'#' * h.level} {h.title} (line {h.line})" for h in heads
        )

    @function_tool
    async def read_note(
        self,
        context: RunContext[CallState],
        path: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> str:
        """Read a note, or a range of its lines, exactly as written. Use it to answer
        questions, to summarize, and to recite.

        Args:
            path: The note's path. Omit to use the note currently open.
            start_line: First line to read, counting from 1. Omit for the start.
            end_line: Last line to read. Omit for the end.
        """
        note = self._note(context, path)
        try:
            ex = self._workspace.read(note, start_line, end_line)
        except WorkspaceError as e:
            raise ToolError(str(e)) from None
        if not ex.text.strip():
            return f"{ex.path} is empty."
        return f"{ex.path}, lines {ex.start_line} to {ex.end_line} of {ex.total_lines}:\n{ex.text}"

    @function_tool
    async def read_section(
        self, context: RunContext[CallState], heading: str, path: str | None = None
    ) -> str:
        """Read one section of a note: the heading and everything under it, exactly as written.

        Args:
            heading: The heading's words, such as "Action items"
            path: The note's path. Omit to use the note currently open.
        """
        note = self._note(context, path)
        try:
            ex = self._workspace.section(note, heading)
        except WorkspaceError as e:
            raise ToolError(str(e)) from None
        return f"{ex.path}, lines {ex.start_line} to {ex.end_line}:\n{ex.text}"

    # -- writing tools -------------------------------------------------------------------------

    @function_tool
    async def create_note(
        self, context: RunContext[CallState], path: str, content: str
    ) -> ToolResult:
        """Create a new note. Fails if one already exists at that path.

        Args:
            path: Where to create it, such as "meetings/2026-11-02.md". Use .md unless told
                otherwise.
            content: The full text of the note, in Markdown
        """
        try:
            self._workspace.create(path, content)
        except WorkspaceError as e:
            raise ToolError(str(e)) from None
        context.userdata.current_note = path
        logger.info("created %s", path)
        return _done()

    @function_tool
    async def append_to_note(
        self, context: RunContext[CallState], content: str, path: str | None = None
    ) -> ToolResult:
        """Add text to the end of a note.

        Args:
            content: The text to add, in Markdown
            path: The note's path. Omit to use the note currently open.
        """
        note = self._note(context, path)
        try:
            self._workspace.append(note, content)
        except WorkspaceError as e:
            raise ToolError(str(e)) from None
        logger.info("appended to %s", note)
        return _done()

    @function_tool
    async def insert_in_note(
        self, context: RunContext[CallState], heading: str, content: str, path: str | None = None
    ) -> ToolResult:
        """Add text at the end of one section of a note, under its heading.

        Args:
            heading: The heading of the section to add to
            content: The text to add, in Markdown
            path: The note's path. Omit to use the note currently open.
        """
        note = self._note(context, path)
        try:
            self._workspace.insert_after_heading(note, heading, content)
        except WorkspaceError as e:
            raise ToolError(str(e)) from None
        logger.info("inserted into %s", note)
        return _done()

    @function_tool
    async def replace_in_note(
        self,
        context: RunContext[CallState],
        find: str,
        replacement: str,
        path: str | None = None,
    ) -> ToolResult:
        """Replace one exact passage of a note with new text. The passage must appear
        exactly once; read the note first to copy it exactly.

        Args:
            find: The exact existing text to replace
            replacement: The new text. Empty to delete the passage.
            path: The note's path. Omit to use the note currently open.
        """
        note = self._note(context, path)
        try:
            self._workspace.replace(note, find, replacement)
        except WorkspaceError as e:
            raise ToolError(str(e)) from None
        logger.info("replaced text in %s", note)
        return _done()


def _done() -> ToolResult:
    """A successful write: kept in the chat history, but no reply is generated for it."""
    return ToolResult("Done.", reply_required=False)


async def _drop_acknowledgments(text: AsyncIterable[str]) -> AsyncIterator[str]:
    """Pass the reply through, unless the whole reply is a bare acknowledgment like "Done."."""
    buffer = ""
    async for chunk in text:
        buffer += chunk
        if len(buffer) > _ACK_MAX_CHARS:
            yield buffer
            buffer = ""
            async for rest in text:
                yield rest
            return
    reply = buffer.strip()
    if reply and not _ACK.match(reply) and not _is_noise(reply):
        yield buffer
    elif reply:
        logger.info("dropped reply %r", reply)


def _is_noise(reply: str) -> bool:
    """A character or two with no letters or digits: a model's stand-in for saying nothing."""
    return len(reply) <= 2 and not any(c.isalnum() and c.isascii() for c in reply)


def open_workspace() -> Workspace:
    return LocalWorkspace(WORKSPACE_ROOT)


def keyterms(workspace: Workspace) -> list[str]:
    """Words the STT should spell right: the agent's name and the notes' names."""
    terms = {ASSISTANT_NAME}
    try:
        for entry in workspace.list():
            stem = entry.path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            for word in re.split(r"[-_\s]+", stem):
                if len(word) > 3 and not word.isdigit():
                    terms.add(word.capitalize())
    except WorkspaceError:
        pass
    return sorted(terms)[:50]


def llm_gateway(
    model: str = LLM_MODEL, reasoning_effort: str | None = LLM_REASONING_EFFORT
) -> openai.LLM:
    """An LLM served by AssemblyAI's LLM Gateway, through its OpenAI-compatible API."""
    api_key = os.getenv("ASSEMBLYAI_API_KEY")
    if not api_key:
        raise ValueError("Set ASSEMBLYAI_API_KEY in .env.local or the environment")
    kwargs = {"reasoning_effort": reasoning_effort} if reasoning_effort else {}
    return openai.LLM(model=model, base_url=LLM_GATEWAY_URL, api_key=api_key, **kwargs)


server = AgentServer()


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load(activation_threshold=VAD_THRESHOLD)


server.setup_fnc = prewarm


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    ctx.log_context_fields = {"room": ctx.room.name}

    workspace = open_workspace()
    logger.info("workspace root %s", WORKSPACE_ROOT)

    tts = assemblyai.TTS(voice=TTS_VOICE)
    tts.prewarm()

    session = AgentSession[CallState](
        userdata=CallState(workspace=workspace),
        stt=assemblyai.STT(
            model="universal-3-6-pro",
            mode=STT_MODE,
            vad_threshold=VAD_THRESHOLD,
            keyterms_prompt=keyterms(workspace),
            prompt="A person dictating and editing their own notes, by file name and heading.",
        ),
        llm=llm_gateway(),
        tts=tts,
        vad=ctx.proc.userdata["vad"],
        turn_handling=TurnHandlingOptions(
            turn_detection="stt",
            endpointing={"min_delay": 0},
            interruption={"resume_false_interruption": True},
        ),
        tts_text_transforms=["filter_emoji", "filter_markdown"],
        use_tts_aligned_transcript=True,
    )

    async def log_usage() -> None:
        logger.info("usage: %s", session.usage)

    ctx.add_shutdown_callback(log_usage)

    await session.start(agent=Assistant(workspace), room=ctx.room)


if __name__ == "__main__":
    cli.run_app(server)
