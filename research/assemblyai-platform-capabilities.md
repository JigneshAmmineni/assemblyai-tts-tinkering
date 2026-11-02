# AssemblyAI platform capabilities for a cascading voice agent

Date: 2026-11-01 (revised; replaces the 2026-10-31 version, which is in git history)
Scope: what AssemblyAI's stack can do for a self-hosted STT -> LLM -> TTS agent with tool access to its own container's file system.

Access note: this revision read AssemblyAI's documentation directly, through its per-section full-text files (`/docs/llms-full/*.txt`), the Voice Agent API pages, and two first-party machine-readable references: `assemblyai.com/llms/models.md` and `assemblyai.com/pricing.md` (both updated 2026-10-27). The October 31 version only had search snippets. The five dashboard links were visited while signed in (section 2.6). Figures are vendor-reported unless noted.

---

## 1. Executive summary

| Stage | Product | Interface | Listed price |
|---|---|---|---|
| Ears | Universal-3.6 Pro Realtime (streaming STT with built-in turn detection) | WebSocket `wss://streaming.assemblyai.com/v3/ws` | $0.45/hr of open session |
| Ears, short clips | Sync STT (one HTTP call per clip) | HTTP | not checked |
| Ears plus cleanup | Dictation API (STT and LLM rewrite in one call) | HTTP multipart | not on the current pricing page ($0.62/hr in launch coverage) |
| Brain | LLM Gateway (OpenAI-compatible, about 50 models) | `POST /v1/chat/completions` | per token, per model |
| Voice | AssemblyAI-TTS-1 (launched 2026-10-27) | WebSocket, HTTP, OpenAI-compatible route | $15 per 1M input characters |
| All-in-one | Voice Agent API | WebSocket `wss://agents.assemblyai.com/v1/ws` | **being retired**; no longer on the pricing page |

What changed since the October 31 report:

1. **The Voice Agent API is being retired, and it does not use AssemblyAI-TTS-1.** Both first-party reference files say so in plain words: don't recommend it for new builds, use Universal-3.6 Pro Realtime plus LLM Gateway plus the TTS API instead, starting from the LiveKit or Pipecat reference agents. The Voice Agent API docs pages are still online and show no retirement notice or date, but the dashboard has already moved on: its Voice Agents section only offers the LiveKit and Pipecat reference agents, and the old Voice Agent playground URL redirects there. For a project whose point is to test the new TTS model, the chained build is the only option that exercises it.
2. **TTS has no markup for emotion or pauses.** Tone comes from the text itself: punctuation, capitalised words, written fillers, stutters and false starts. SSML, emotion tags, speed and volume control, custom pronunciation dictionaries and non-verbal sounds are listed as not available at launch, with no dates.
3. **Streaming STT takes the agent's replies as context** through a documented `agent_context` parameter, and carries the last five finalised user turns automatically.
4. **Dictation** covers 32 languages (not 19), and has a second endpoint for finished recordings up to 20 minutes. Its rewrite step can take a full LLM Gateway request instead of a plain-English instruction.
5. **Free start:** $50 of credits at signup with no credit card. The free tier allows 5 new streaming sessions per minute (100 on pay-as-you-go), and TTS sessions share that limit.

The build that fits your goal is a cascade you orchestrate yourself: streaming STT, then your own agent loop calling LLM Gateway with file-system tools, then the TTS WebSocket. AssemblyAI ships that exact cascade as two MIT-licensed reference agents, one on Pipecat and one on LiveKit.

---

## 2. Product by product

### 2.1 Streaming speech-to-text: Universal-3.6 Pro Realtime

- Default and recommended streaming model (`speech_model=universal-3-6-pro`). 32 languages with native code-switching, language detection, and disfluencies kept in the transcript. Universal-3.5 Pro is still supported with 18 languages. The cheaper Universal-Streaming English and Multilingual models ($0.15/hr) lack prompting and conversation context.
- **Turn detection is built in** and entity-aware: it holds the turn open while the user is mid-number, mid-email or mid-address. Turn settings can be changed per question, for example loosened while capturing an entity and restored afterwards.
- **Prompting:** keyterms (up to 100, included in the price) for known vocabulary, plus a free-text `prompt` (beta, +$0.05/hr) describing the situation. Both can be replaced mid-session with an `UpdateConfiguration` message.
- **Conversation context:** pass what your TTS just said as `agent_context`, at connect time for the greeting and with `UpdateConfiguration` after every reply. The model then expects the right kind of answer, so "user at assemblyai dot com" comes back as an email address. Prior finalised user turns are carried forward automatically: 5 entries, 1,750 characters at most, per session only.
- Add-ons on 3.6 Pro: Voice Focus noise suppression (+$0.10/hr), diarization (+$0.12/hr), medical mode (+$0.15/hr). Real-time translation, PII redaction and profanity filtering are documented too.
- Billing is per second of **open WebSocket**, not audio sent, so idle sessions cost money.
- Data zones: an edge endpoint that routes to the nearest region, plus pinned US and EU endpoints. Temporary tokens let a browser connect without your API key.
- The docs have a guide for applying an LLM Gateway prompt to each final turn, which is one way to bolt cleanup onto streaming.

### 2.2 Dictation API (STT plus LLM cleanup in one call)

- Two endpoints. `transcribe/live` accepts audio while the person is still talking (up to 120 s) and returns one finished result when the upload closes. `transcribe` takes a finished recording up to 20 minutes. Neither returns partials.
- Runs on Universal-3.5 Pro across 32 languages. A connection pre-warming guide covers opening the HTTPS connection before the user starts speaking.
- Request fields: `language_codes`, `stt_prompt` (situation description), `keyterms_prompt` (exact terms), `llm_instruction` (plain-English rewrite task that replaces the default cleanup), `rewrite_mode` (`fast` by default, or `smart` for better adherence to formatting instructions at higher latency). For full control, send `llm` instead of `llm_instruction`: a complete LLM Gateway chat-completions request or a saved prompt.
- Default cleanup removes fillers, resolves self-corrections to what the speaker settled on, and fixes punctuation and capitalisation while keeping the speaker's phrasing. The docs' own example turns "move the the meeting to thursday i think friday works better actually" into "Can we move the meeting to Friday? That works better."
- Response carries both the verbatim `text` and the rewrite.
- AssemblyAI's open-source macOS app **Blurt** (github.com/AssemblyAI/blurt) is a Wispr-Flow-style client on this API and the best public reference for context-aware dictation cleanup.

### 2.3 LLM Gateway

- OpenAI-compatible `https://llm-gateway.assemblyai.com/v1/chat/completions` with US, EU and global routing. Global routing is the listed price; pinning a region costs 10% more.
- About 50 models from Anthropic, OpenAI, Google and Qwen. Pricing examples per 1M tokens (input / output): Claude 4.6 Sonnet $3 / $15, Claude 4.5 Haiku $1 / $5, GPT-5-Mini $0.25 / $2, Gemini 2.5 Flash $0.30 / $2.50. The docs' own examples default to `claude-sonnet-4-6`; the reference agents default to `gemma-4-31b`.
- Features that matter for this agent: tool calling in OpenAI shape for every provider (note that `finish_reason` stays provider-native: `tool_use` for Claude, `tool_calls` for OpenAI), a documented agentic loop that you run client-side, a `json-repair` post-processing step for malformed tool arguments, structured outputs, model fallbacks, prompt caching on Anthropic, OpenAI and Google models, and saved prompts.
- The gateway does not run your tools. Your process executes each tool call and sends the result back, which is what you want for file-system access.

### 2.4 Text-to-speech: AssemblyAI-TTS-1

**Positioning.** Conversational speech for voice agents, mostly phone agents. AssemblyAI says outright that it is not built for voiceover, audiobooks or long-form audio. Time to first audio is "about 90 ms", which AssemblyAI calls an estimate.

**Voices and languages.**
- Six languages: English, Spanish, French, German, Italian, Portuguese. Every voice can speak all six once you set `language`, but a voice sounds best in the language it was recorded in, and text in a language other than the session's comes out mispronounced. The API does not detect language. `language` takes full names such as `spanish`, unlike the STT APIs, which take codes.
- 4,000+ catalog voices with `aai-` slugs (examples: `aai-audrey`, `aai-sara`, `aai-titus`, `aai-constanza` for Mexican Spanish). Eleven built-in voices are always loaded (`aai-jane` is the default); other voices load on first use, so the first session with a cold voice waits slightly longer. The old `voice=` parameter is retired; use `voice_id`.
- Instant voice cloning in the dashboard from about 25 seconds of a consenting speaker (the playground version asks you to read two short sentences), with a consent period you renew and a biometric data addendum. A cloned voice only works in the data zone where it was created. Cloned voices cost the same as library voices. The sources disagree on languages: the docs say a clone can speak all six when `language` is set, while the dashboard quickstart says a clone speaks only the language it was recorded in. Test before relying on either.

**Controlling delivery with text.** No SSML, tags or speed control. Instead:
- `!` for emphasis, `?` for question intonation, `?!` for surprise.
- Commas or ellipses for short pauses; stacking them does not lengthen the pause.
- A trailing `--` for a sudden cutoff.
- ALL CAPS on a word to stress it.
- Written fillers ("It's, uh, right here"), stutters ("I c-c-can't"), false starts ("That- that is the one").
- Brackets are read aloud, so `[pause]` or `[laughs]` is spoken as a word. Strip such tags from LLM output.
- The server normalises currencies, dates with years, phone numbers, addresses, units, emails and URLs, and drops emoji and Markdown. File paths and hex numbers are read symbol by symbol, which matters for an agent that talks about files.
- The prompting guide recommends having the LLM write like a person on a call: soft openings ("Yeah, so..."), one small stumble per reply, short first turns, no internal abbreviations.

**Interfaces.**
- WebSocket `wss://tts.us.assemblyai.com/v1/ws` (EU: `tts.eu.assemblyai.com`): one session per conversation. Frames: `Generate` (text, up to 2,000 characters), `Flush`, `Cancel` for barge-in, `KeepAlive`, `Terminate`; the server sends `Begin`, audio, `FlushDone`, optional `WordBoundaries`, `Error`.
- HTTP `POST /v1/speech`: up to 5,000 characters, streamed or buffered, with a `Server-Timing` header that reports server-side time to first audio. A server-sent-events variant returns word timings.
- OpenAI-compatible route, so OpenAI SDK code works with a new base URL.
- Native output is 24 kHz 16-bit PCM; other rates and mu-law / a-law are converted server-side. MP3 adds about 46 ms of encoder silence at 24 kHz, so use PCM for an agent.
- Native plugins for LiveKit (`assemblyai.TTS`) and Pipecat (`AssemblyAITTSService`), and Python and JavaScript SDKs.

**Latency rules from the docs.**
- Open the TTS session when the call starts, not when the first reply is ready.
- Forward LLM tokens as they arrive, with their spaces, and send `Flush` at the end of every sentence. Without a flush, a short first sentence waits for the next one: the server ignores sentence ends in roughly the first 50 characters. Never flush per token; that breaks prosody and trips the control-frame limit.
- Keep the first sentence short.
- Run the agent in the same data zone as STT and TTS (`tts.us` is us-east-1, `tts.eu` is eu-north-1).

**Limits.** Session up to 1 hour; 120 s idle timeout (configurable down to 5 s); about 100 characters per second of sustained text intake after a 1,500-character burst; 8,000 characters of unspoken backlog; 20 control frames per second.

**Word boundaries** give per-word timings. On barge-in, the reference agents cut the chat history at the last word the user actually heard.

### 2.5 Voice Agent API (being retired)

Still documented and usable, but AssemblyAI's own references say not to start new builds on it, and it does not run AssemblyAI-TTS-1. For the record, it offers:
- One WebSocket carrying audio both ways, with STT, a managed LLM, TTS, turn detection and barge-in on AssemblyAI's side. Reusable agents are stored with `POST /v1/agents` (name, system prompt, voice, greeting, tools, optional `llm`).
- **Two tool types:** HTTP tools, which AssemblyAI calls for you, and function tools, which arrive as `tool.call` events for your code to answer with `tool.result` after `reply.done`. Function tools are how this API would reach your container's file system. Tool parameters use JSON Schema, and `enum`, `pattern`, `examples` and `format` also inform turn detection, so the agent waits for a complete phone number before replying. Execution modes are `interactive` (keeps talking, "let me check") and `hold` (goes quiet, for slow operations).
- Bring your own OpenAI-compatible LLM, or point it at LLM Gateway.
- Session history with downloadable recordings and JSON timelines, Twilio SIP phone numbers, DTMF capture for card entry, and simulated-caller testing with Bluejay and Cekura.
- Closing the socket without `session.end` keeps the session resumable, and billable, for 30 seconds.

The design ideas here (schema-aware turn detection, interactive versus hold tools, history cut at the heard word) are worth copying into a chained build.

### 2.6 Dashboard pages you linked (visited 2026-11-01, signed in)

| Link | What it actually is |
|---|---|
| `dashboard/playground/text-to-speech` | TTS playground. Settings: model (AssemblyAI TTS-1 only), sample rate, voice, language. Three sample scripts (appointment scheduling, billing and payments, support handoff), a 2,000-character text box, and Audio, Code and API Response tabs. The Code tab gives a ready-to-run HTTP or WebSocket request for the current voice. A "Clone a voice" panel makes a voice from two sentences you read aloud. Speed, emotion tags and pronunciation dictionary are shown as "Coming soon". |
| `get-started?product=tts` | TTS quickstart: a three-step checklist (copy key, pick a voice, run the snippet) with cURL, Python and JavaScript versions for HTTP and WebSocket. Links to the prompting guide, voice library, cloning, the playground, per-request session logs and the biometric data addendum. |
| `dashboard/agent` | **Not a voice agent manager.** It is an AI coding assistant ("What can I help you build with AssemblyAI?") that writes code into a side canvas, with starters such as "Turn text into speech for a voice agent" and "Build a dictation app". It shows credits used, and AssemblyAI says chat content is shared with its team, so keep sensitive details out of it. |
| `get-started?product=voice-agent` | Quickstart for the **LiveKit and Pipecat reference agents**, not the Voice Agent API. Shows each repo's full agent file. LiveKit runs in your terminal (`uv run src/agent.py console`) or joins LiveKit Cloud rooms (`dev`). Pipecat serves a call page at `localhost:7860`, or uses a Daily room or a Twilio number. |
| `get-started?product=dictation` | A combined Sync STT and Dictation quickstart, led by a long prompt meant for coding agents. Useful facts in it: audio from 80 ms to 20 minutes, file bytes only (no URL), no temporary-token flow (browser apps must proxy through a server), and a docs MCP server at `https://mcp.assemblyai.com/docs`. |

Other dashboard pages seen on the way: the voice library at `dashboard/text-to-speech/voices` (filters for gender, accent, age, language and tags; Recommended, Public, My Voices and Liked tabs; community votes; "Create Voice Clone"), and a Text to Speech > Logs page. The sidebar's Voice Agents section holds only "Get Started", and `dashboard/playground/voice-agent` redirects to the reference-agent quickstart.

Caution: the playground's Code tab and the quickstart snippets embed your real API key. Don't screenshot or paste them anywhere public.

### 2.7 Developer tooling

- Python and Node SDKs cover streaming STT, Dictation, TTS sessions and LLM Gateway.
- The `assembly` CLI (github.com/AssemblyAI/cli) includes dictation, TTS and terminal voice-agent commands (command list from the previous report, not re-checked).
- An integration prompt for coding agents at `docs/agent-instructions.md`, plus `llms.txt` and per-section full-text files.
- **Reference agents** (MIT, updated 2026-10-28): `assemblyai-pipecat-reference-voice-agent` and `assemblyai-livekit-reference-voice-agent`. Both wire Universal-3.6 Pro to LLM Gateway (`gemma-4-31b`) to AssemblyAI TTS with word timings. Defaults: `balanced` turn detection, 0.2 speech threshold, voice Audrey (Pipecat) or Keegan (LiveKit). Each building block (voice, turn detection, VAD, Voice Focus, keyterms, languages, medical mode, LLM) is a skill in `skills/`, and an `AGENTS.md` tells Claude Code or Cursor how to customise the agent.
- `voice-standard-bench` benchmarks gateway models on voice post-processing tasks, useful for picking the brain or cleanup model.

---

## 3. LiveKit vs Pipecat

Both are open-source frameworks for orchestrating a real-time voice agent: they move audio between the user and your STT, LLM and TTS services, handle turn-taking and interruptions, and stream everything so replies start quickly. Neither provides models. For a two-party STT -> LLM -> TTS agent they are interchangeable, and AssemblyAI ships the same reference agent on both.

| | LiveKit Agents | Pipecat |
|---|---|---|
| Maintainer, licence | LiveKit, Apache-2.0 | Daily, BSD-2-Clause |
| Core idea | An agent joins a WebRTC **room** on a LiveKit media server (LiveKit Cloud or self-hosted) | A **pipeline** of frame processors: transport -> STT -> LLM -> TTS -> transport |
| Media server | Required for real clients; a `console` mode talks to you in the terminal without one | Not required; transports include peer-to-peer WebRTC, Daily, LiveKit, plain WebSocket and telephony serializers |
| Languages | Python and Node | Python (client SDKs in JS and others) |
| Strengths | Browser and mobile clients, multi-party rooms, video and avatars, native SIP telephony | Explicit control of every frame, simple local loops, the widest vendor catalogue |
| Hosting | LiveKit Cloud or your own container | Pipecat Cloud or your own container |

Choose LiveKit if you want a polished browser or phone client and expect more than two participants. Choose Pipecat if you want the simplest local loop with no media server and fine control of the pipeline. Pipecat can use LiveKit as a transport, but LiveKit Agents needs a LiveKit server for anything beyond its terminal `console` mode.

---

## 4. Recommended architecture for the file-system agent

```
mic/browser --PCM--> Universal-3.6 Pro Realtime (WebSocket; turn detection; agent_context = last reply)
                       | final turns
                       v
             agent loop (your process, inside the container)
               |- LLM Gateway chat.completions, streaming
               |    tools: list_dir, read_file, write_file, search, run_cmd (sandboxed root, allow-list)
               |    you execute each tool call and append the result
               '- streams reply tokens, stripped of Markdown and bracket tags
                       | tokens, Flush at each sentence end
                       v
             AssemblyAI-TTS-1 WebSocket (one session per conversation, word_boundaries on)
                       | 24 kHz PCM
                       v
                   speaker/browser
   barge-in: user starts speaking -> TTS Cancel -> cut history at last heard word
   after each reply: UpdateConfiguration(agent_context = what was spoken)
```

Notes:
- Start from the Pipecat reference agent (no media server needed for local testing) and add the tools there; switch to the LiveKit one later if you want a hosted browser client.
- Keep the system prompt's spoken-style rules from the TTS prompting guide, and tell the model to describe file paths in words rather than reading them out symbol by symbol.
- Tools that take seconds (a long search or command) should say a short "let me check" first, the same idea as the Voice Agent API's interactive mode.
- Optional experiment: a push-to-talk input mode through the Dictation API, to compare cleaned versus verbatim transcripts as agent input.

---

## 5. Sources

AssemblyAI documentation, read directly on 2026-11-01:
- Docs index and section files: https://www.assemblyai.com/docs/llms.txt (Text to Speech parts 1 to 4, Dictation API, Real-time STT parts 1 and 2, LLM Gateway parts 1 and 2)
- TTS: https://www.assemblyai.com/docs/tts/getting-started/quickstart, https://www.assemblyai.com/docs/tts/getting-started/optimizing-accuracy-and-latency, https://www.assemblyai.com/docs/tts/voices, https://www.assemblyai.com/docs/tts/prompting-guide, https://www.assemblyai.com/docs/tts/limits
- Streaming STT: https://www.assemblyai.com/docs/streaming/select-the-speech-model, https://www.assemblyai.com/docs/streaming/universal-3-5-pro/context-carryover
- Dictation: https://www.assemblyai.com/docs/dictation, https://www.assemblyai.com/docs/dictation/transcript-rewriting
- LLM Gateway: https://www.assemblyai.com/docs/llm-gateway/tool-calling, https://www.assemblyai.com/docs/llm-gateway/agentic-workflows
- Voice Agent API: https://www.assemblyai.com/docs/voice-agents/voice-agent-api (and its tools, connect-your-own-llm, events-reference and session-history pages)
- Model and pricing references: https://www.assemblyai.com/llms/models.md, https://www.assemblyai.com/pricing.md, https://www.assemblyai.com/pricing

GitHub, read directly: AssemblyAI/assemblyai-livekit-reference-voice-agent, AssemblyAI/assemblyai-pipecat-reference-voice-agent, AssemblyAI/blurt, AssemblyAI/cli, AssemblyAI/voice-standard-bench.
