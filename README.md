# assemblyai-tts-tinkering

A voice assistant that works inside a folder of notes, built to try AssemblyAI's full voice stack: Universal-3.6 Pro streaming speech-to-text, an LLM through the LLM Gateway, and AssemblyAI-TTS-1, orchestrated by LiveKit Agents. You talk to it like a work assistant: it lists, searches, reads and recites your Markdown and text notes, creates new ones, appends, and makes exact edits you dictate. When a task succeeds it says nothing.

```
you ──▶ Universal-3.6 Pro ──▶ LLM Gateway ──────▶ AssemblyAI TTS ──▶ you
        speech-to-text,        Gemma 4 31B now,      word-timed
        end of turn            tool calls            speech
                                    │
                                    ▼
                          /workspace (your notes)
```

Started from AssemblyAI's [LiveKit reference voice agent](https://github.com/AssemblyAI/assemblyai-livekit-reference-voice-agent) (MIT, see `LICENSE-reference-agent`).

## Layout

- `src/agent.py`: the whole agent. Settings at the top, then `Assistant` (instructions and tools), then `entrypoint`, which builds the speech-to-text -> LLM -> text-to-speech pipeline.
- `src/workspace.py`: the files the agent can touch. `Workspace` is the small interface the tools use; `LocalWorkspace` implements it over one folder. A backend for S3 or a git checkout implements the same methods and the agent doesn't change.
- `sample-workspace/`: a few notes to try it on.
- `tests/`: unit tests for the workspace and the quiet filter (no key needed), and LLM-judged tests of the agent (need `ASSEMBLYAI_API_KEY`).
- `research/`: background reports on AssemblyAI's platform and on how Wispr Flow works.

## Run it

Put your keys in `.env.local` (see `.env.example`). Everything runs in Docker, so nothing is installed on your machine.

```bash
docker compose up --build
```

That starts the agent against LiveKit Cloud, with `./sample-workspace` mounted at `/workspace`. It registers as `assistant-local` (the cloud deployment is `assistant`). Talk to it from LiveKit Cloud's Agent Console (project > Agents > Console, pick `assistant-local`), or from any LiveKit frontend or phone number that dispatches that agent name.

To work on a different folder of notes, set `WORKSPACE_DIR` for compose:

```bash
WORKSPACE_DIR=/path/to/your/notes docker compose up --build
```

Without Docker, with [uv](https://docs.astral.sh/uv/) and Git LFS installed: `uv sync`, then `uv run src/agent.py console` to talk to it in the terminal (needs only the AssemblyAI key), or `uv run src/agent.py dev` to connect to LiveKit Cloud.

## Configure it

All through environment variables, so the same image works anywhere:

| Variable | Default | What it does |
|---|---|---|
| `WORKSPACE_ROOT` | `/workspace` in the container, `./sample-workspace` locally | The folder of notes |
| `AGENT_NAME` | `assistant` (`assistant-local` under compose) | The name LiveKit dispatches the worker by |
| `TTS_VOICE_ID` | Audrey | A voice id from the dashboard's voice library, or a cloned voice's id |
| `ASSISTANT_NAME` | `Audrey` | The name the agent answers to |
| `LLM_MODEL` | `gemma-4-31b` | Any tool-capable model on the LLM Gateway. The plan is `claude-sonnet-5-5`; see below |
| `LLM_REASONING_EFFORT` | `low` | Thinking depth; higher is smarter and slower to start speaking |

To use a cloned voice, record one in the [AssemblyAI dashboard](https://www.assemblyai.com/dashboard/text-to-speech/voices), copy its id into `TTS_VOICE_ID`, and set `ASSISTANT_NAME` to whatever you want to call it.

### Why Gemma and not Claude

The agent was designed for Claude Sonnet 5.5 with thinking on at low effort. On 2026-11-01 the account's Gateway tier only served AssemblyAI-hosted models; every Anthropic, OpenAI and Google model returned "Your account does not have access to this LLM Gateway model", which looks like the free tier before a card is on file. Once the account can use them, set `LLM_MODEL=claude-sonnet-5-5` (and `JUDGE_MODEL=claude-sonnet-4-6` for the tests) and nothing else changes. If you'd rather spend Anthropic credits, LiveKit has an `anthropic` plugin that drops in where `llm_gateway()` is; that path isn't wired up here.

## Test it

```bash
docker build --target test -t notes-agent-test .
docker run --rm --env-file .env.local notes-agent-test
```

The workspace and quiet-filter tests always run. The agent tests talk to the LLM Gateway and are skipped without a key. Run them twice when you change the instructions: an LLM doesn't answer the same way every time.

## Deploy it

The image runs on any container host given `ASSEMBLYAI_API_KEY` and the `LIVEKIT_*` variables, with your notes mounted at `/workspace`. On LiveKit Cloud:

```bash
lk agent create --secrets-file .env.local
```

LiveKit Cloud has no persistent volumes, so there the agent works on the sample notes baked into the image. For your own notes, run the image on a host that can mount them (a VM with Docker, Fly.io, ECS, Cloud Run with a GCS volume), or add a `Workspace` backend that reads from object storage.

## Talking to it

The agent is quiet on purpose. Things to say:

- "What notes do I have?"
- "Read me the action items from the October 28 standup, word for word."
- "Who is on the Atlas team?"
- "Add 'book the offsite venue' to the todo list." (it does it silently)
- "In the Atlas note, under Open questions, add: do we need SOC 2 before the beta?"
- "Change 'March 15' to 'March 22' in the Atlas note."
- "Create a note called ideas with: try a weekly office hours slot for design partners."
- "Explain the risks section." (it elaborates only when asked)
