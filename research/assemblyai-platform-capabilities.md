# AssemblyAI platform capabilities for a cascading voice agent

Date: 2026-10-31
Scope: what AssemblyAI's stack can do for a self-hosted STT -> LLM -> TTS agent that has tool access to its own container's file system. Sources are AssemblyAI's own docs/blogs (reached via search snippets), AssemblyAI's public GitHub repos and SDK READMEs (read directly), and third-party launch coverage. Figures are vendor-reported unless noted.

Access note: `assemblyai.com` and `docs.livekit.io` / `docs.pipecat.ai` are blocked by this cloud session's network policy, so docs pages were read through search snippets and the GitHub mirrors of the SDKs and reference agents. The four dashboard links require a login and could not be visited. Anything marked "(unverified)" could not be confirmed against the primary page.

---

## 1. Executive summary

AssemblyAI now sells every stage of a voice agent under one API key:

| Stage | Product | Interface | Price (listed) |
|---|---|---|---|
| Ears | Universal-3.6 Pro Realtime (streaming STT, built-in end-of-turn) | WebSocket (`streaming.v3`) | $0.45/hr |
| Ears, short-form | Sync STT (clips <= 120 s, one HTTP call) | HTTP POST | n/a in sources |
| Ears + cleanup | Dictation API (STT + LLM rewrite in one call) | HTTP POST (multipart, chunked upload) | $0.62/hr incl. rewrite |
| Brain | LLM Gateway (OpenAI-compatible, ~33-50 models: Claude, GPT, Gemini, Qwen, Gemma) | `POST /v1/chat/completions` | per-model |
| Voice | AssemblyAI-TTS-1 (GA 27 Oct 2026) | HTTP, WebSocket, OpenAI-compatible | $15 / 1M chars |
| All-in-one | Voice Agent API (STT + LLM + TTS + turn-taking + tools behind one socket) | WebSocket `wss://agents.assemblyai.com/v1/ws` | $4.50/hr flat |

Two ways to build the agent you described:

1. **Cascading / chained (full control).** Streaming STT -> your own agent loop (LLM Gateway or any LLM) -> TTS WebSocket. You own the tool loop, so file-system tools are ordinary function calls in your process. AssemblyAI ships reference implementations of exactly this for both Pipecat and LiveKit.
2. **Voice Agent API (least code).** One WebSocket; AssemblyAI runs STT/LLM/TTS server-side and emits `tool.call` events. You run the tool (e.g. read a file in your container) and send `tool.result`. This still gives your agent file-system access through client-side tools, but the LLM and orchestration are AssemblyAI's.

For "explore the full AssemblyAI stack" the chained route exercises more of the products (STT, LLM Gateway, TTS, Dictation as an optional input mode). The Voice Agent API is worth a second, smaller experiment.

---

## 2. Product-by-product detail

### 2.1 Streaming speech-to-text: Universal-3.6 Pro Realtime

- Recommended streaming model; 32 languages; keyterms prompting (up to 100 terms); native free-text `prompt` for context, updatable mid-session.
- **End-of-turn detection is built in** and entity-aware: it holds the turn open while the user is mid-number, email, address or code. Each turn carries a 0-1 end-of-turn confidence you can threshold. Reported precision 77.9% (up from 74.1% on 3.5 Pro), recall ~92-93%.
- Turn controls exposed in integrations: `min_turn_silence` (speculative check), `max_turn_silence` (forced end), turn-detection profiles (`balanced` is the reference default), speech threshold (0.2 default), optional server-side noise suppression ("voice focus").
- Latency claims vary by what is measured: ~150 ms P50 on the product page, 537 ms median end-of-turn latency in the 3.6 blog, 307 ms median time-to-final in a Vapi/Pipecat measurement. Treat "sub-300 ms partials, ~0.5 s to final" as the realistic planning number.
- **Conversation/agent context (Universal-3.5 Pro Realtime onward):** the streaming model can take the agent's last question as input so it recognises likely answers (dates, yes/no, names). This is directly useful to a cascading agent: feed the TTS text you just spoke back into the STT session as context.
- `llm_gateway` parameter on the streaming session: run an LLM Gateway prompt on each final turn server-side (documented for summaries/action items, but the prompt is free-form, so it can be a cleanup prompt).
- SDK: `RealTimeTranscriber` / `AsyncRealTimeTranscriber` (`assemblyai.streaming.v3`), events `Begin`, `Turn`, `Termination`, `Error`; `force_endpoint()` to end a turn manually; `ChannelStreamer` to mix mic + system audio; `create_temporary_token()` for browser clients. Model id strings in the wild: `universal-3-6-pro`, `u3-rt-pro`, `universal-3-5-pro` (check the current docs before hardcoding).

### 2.2 Sync STT (short clips)

- `aai.SyncTranscriber`: WAV or raw PCM, <= 120 s and <= 40 MB, one request, one response. Used by the CLI's `assembly dictate` before the Dictation API existed. Good for push-to-talk input where you do not need partials.

### 2.3 Dictation API (STT + LLM cleanup in one call)

- Endpoint `POST https://dictation.assemblyai.com/v1/transcribe/live`, multipart with the config part first; audio is uploaded while the person is still speaking and one finished result is returned when the stream closes. It is **not** a streaming-output API: no partials, one answer per utterance.
- Built on Universal-3.5 Pro (3.6 per newer pages); 19 languages per docs (pricing page says 32, likely stale); <= 120 s per request. Launched ~20 Sept 2026. $0.62/hr including the LLM rewrite. Launch coverage quotes ~134 ms median added latency for the rewrite (third-party, unverified).
- Request fields: `language_codes`, `stt_prompt` (<= 6,000 chars, describes the situation), `keyterms_prompt` (<= 100 terms / 8,000 chars), `llm_instruction` (<= 2,048 chars; **replaces** the default cleanup, so specify everything you want), `rewrite_mode` = `fast` (default) or `smart` (better formatting adherence, higher latency), `sample_rate` + `channels` for raw PCM.
- Response: `text` (verbatim), `llm_response` (rewrite or null), `llm_error`, `final_text`, `session_id`.
- Default cleanup resolves self-corrections ("Tuesday, no, Wednesday" -> "Wednesday"), removes fillers, fixes punctuation, honours spoken commands like "new paragraph".
- AssemblyAI's own open-source macOS app **Blurt** (github.com/AssemblyAI/blurt, Swift) is a Wispr-Flow-style client on this API. It sends, per request: the last ~100 dictations of the session (<= ~4,096 chars), a short run of text before the cursor (never from password fields), key terms and a user-chosen style instruction. It does **not** send app name, window title or selection. It pre-warms the HTTPS connection on key-down and reports ~1 s typical end-to-end. This is the closest public reference for "context-aware dictation cleanup" and is relevant to the Wispr Flow research.
- CLI: `assembly dictate` (signal-driven, prints cleaned text on SIGTERM).

### 2.4 LLM Gateway

- OpenAI-compatible: `https://llm-gateway.assemblyai.com/v1/chat/completions` (EU: `llm-gateway.eu.assemblyai.com`). Works with the OpenAI SDK by swapping `base_url`. Streaming supported; `fallback_config` for model fallbacks; automatic retry on 5xx.
- Model catalogue: docs say 25+, the live pricing page lists 33 (9 Anthropic, 12 OpenAI, 9 Google, 3 Qwen), reference agents say ~50 and default to `gemma-4-31b`. Example ids seen: `claude-sonnet-4-6`, `claude-sonnet-5`, `gpt-5.2`. OpenAI models are US-only; Claude and Gemini are available in the EU.
- Tool calling is supported (the reference agents use it for `get_current_time`). This is where a file-system tool set plugs in.
- SDK: `aai.LLMGateway` with `models.list()`, `chat.completions.create()` (streaming), and `understanding.create()` for speech-understanding over a transcript.
- Open-source companion: `voice-standard-bench` (Go) benchmarks gateway LLMs on summarisation, extraction, text correction and dictation command handling, with TTFT and cost-per-quality. Useful for picking the cleanup/brain model.

### 2.5 Text-to-speech: AssemblyAI-TTS-1

- GA announced 27 Oct 2026 (this is the "new TTS model"). Positioned for voice agents: ~90 ms time-to-first-audio on the pricing page, 47 ms median TTFB in AssemblyAI's own cross-vendor benchmark. $15 per 1M characters, no per-voice, concurrency or minimum fees; "unlimited concurrency without an annual contract" (vendor claim).
- Languages: English, Spanish, French, German, Italian, Portuguese; every voice speaks all six, so one voice can switch language mid-conversation. More languages "in coming weeks".
- Voices: 4,000+ library voices (per AssemblyAI's reference-agent READMEs) plus instant voice cloning from an uploaded recording, managed in the dashboard voice catalog. Slugs look like `aai-jane`, `aai-sara`, `aai-alba`, `aai-michael`; defaults in the reference agents are "Keegan" (LiveKit) and "Audrey" (Pipecat). Cloned voices carry a biometric-consent flag (`extend_biometric_consent`) and an expiry.
- Three interfaces:
  - HTTP `POST https://tts.us.assemblyai.com/v1/speech` (one-shot; `synthesize()` for full audio or `stream()` for chunks; mp3 available here only).
  - WebSocket `wss://tts.us.assemblyai.com/v1/ws?voice_id=...&sample_rate=24000&encoding=pcm_s16le` for live conversations: one session per conversation, one request per turn. Frames: `Begin`, `Generate` (send text, <= 2,000 chars/frame), `Flush`, `Cancel` (barge-in: drops queued text), `KeepAlive`, `Terminate`; server sends audio, `FlushDone`, optional `WordBoundaries`, `Error`. Limits: ~100 chars/s intake after a 1,500-char burst, <= 8,000 unspoken chars buffered, 1-hour session max, 5-120 s inactivity timeout. Only PCM s16le / mu-law / a-law over the socket.
  - OpenAI-compatible route `https://tts.us.assemblyai.com/v1/openai` (drop-in for code written against OpenAI's speech endpoint).
- Audio: native 24 kHz; also 8k/16k/22.05k/44.1k/48k (resampled); encodings pcm_s16le, pcm_mulaw, pcm_alaw, mp3 (HTTP only); container raw or wav.
- **Word boundaries** (`word_boundaries=true`) give per-word timings per request, which the reference agents use so that on interruption the chat history only records what the user actually heard. Important for a correct barge-in implementation.
- EU residency: `tts.eu.assemblyai.com`.
- SDKs: Python `aai.TextToSpeech` / `aai.TTSSession` (`speak`, `generate`, `flush`, `cancel`), `aai.TTSConfig`; Node `client.tts.synthesize/stream/session`, `createTemporaryToken()` for browsers. LiveKit (`livekit-plugins-assemblyai`) and Pipecat (`pipecat-ai[assemblyai]`, plus a portable `assemblyai_tts.py` in the reference repo) have native TTS plugins.
- Dashboard: a Text-to-Speech playground (pick voice, type text, listen) and the voice catalog / cloning UI live there (the TTS and `get-started?product=tts` links you gave).
- CLI: `assembly speak` (auto-assigns voices per `Speaker A:` label), `assembly dub`.

### 2.6 Voice Agent API (unified speech-to-speech)

- Launched 30 Apr 2026. One WebSocket (`wss://agents.assemblyai.com/v1/ws`), audio in / audio out, with STT (Universal-3.x Pro Realtime), a managed LLM, TTS, turn detection, barge-in, noise suppression and tool calling handled server-side. Audio is PCM16 mono 24 kHz, base64 in `input.audio`. $4.50/hr ($0.075/min) per second of open session, covering STT + managed LLM + TTS + hosting.
- Configure inline via `session.update` (first message; `system_prompt` is mutable mid-session; voice/output format are immutable after `session.ready`) or bind a stored agent by `agent_id`. Stored agents: `POST/PUT/GET /v1/agents` (name, system prompt, voice required). Always send `session.end`; closing the socket leaves the session resumable and billable for 30 s.
- Events: 4 client -> server (`session.update`, `input.audio`, `tool.result`, `session.end` / `session.resume` depending on page) and 12 server -> client, including `session.ready`, `session.updated`, `input.speech.started/stopped`, `transcript.user.delta`, `transcript.user`, `reply.started`, `reply.audio`, `transcript.agent` (now word-by-word per changelog), `reply.done` (status `interrupted` on barge-in), `tool.call`, `session.ended`. Tool results carry an `is_error` flag (recent changelog).
- **Tools:** two kinds, same JSON-Schema `parameters`, `description`, `execution_mode`, `timeout_seconds`.
  - *Client-side tools*: agent emits `tool.call {call_id, name, arguments}`; you run it and reply `tool.result {call_id, result:<JSON string>}`, recommended from the `reply.done` handler. **This is how a Voice-Agent-API build would get file-system access to your container.**
  - *HTTP tools*: AssemblyAI calls your HTTP endpoint directly; header values and `llm[].api_key` are write-only.
- **Bring your own LLM:** set the agent's `llm` field to any OpenAI-compatible `/chat/completions` endpoint (your own, or point `base_url` at LLM Gateway to choose Claude/GPT/Gemini). Latency then depends on your endpoint; Gateway usage is billed separately.
- Telephony: Twilio SIP trunk example (`voice-agent-api-twilio-example`), jambonz and Agora integrations; LiveKit blog shows multi-user browser rooms bridged to the API.
- Testing: Cekura integration for simulated phone calls. Starter repos (`voice-agent-starter-python/js`, stdlib only) define an agent as one JSON file, publish it, serve a browser test page that mints session tokens, and attach a Twilio number. The dashboard `agent` tab you linked is where stored agents are listed/created (inferred from the manage-agents docs; not visited).
- Migration guides exist from OpenAI Realtime API.

### 2.7 Dashboard pages you linked (not visited; inferred)

| Link | What it most likely is |
|---|---|
| `dashboard/playground/text-to-speech` | TTS playground: pick a library/cloned voice, type text, listen; voice catalog + cloning |
| `get-started?product=tts` | TTS quickstart (API key, curl/SDK snippet, link to playground) |
| `dashboard/agent` | Stored Voice Agent API agents (create/edit system prompt, voice, tools; test) |
| `get-started?product=voice-agent` | Voice Agent API quickstart (starter repos, WebSocket snippet) |
| `get-started?product=dictation` | Dictation API quickstart (`transcribe/live` snippet, Blurt/CLI links) |

To have me walk these page by page, either (a) allow `www.assemblyai.com` and `assemblyai.com` in this environment's Network access settings (still no login, so the public docs only), or (b) run this in the Claude desktop app where the built-in browser pane is available and you can sign in. The built-in browser is not available in this cloud session, and your computer's Remote Control folders are not offered to cloud sessions, so the session cannot be linked to it.

### 2.8 Developer tooling

- Python SDK `assemblyai` (>=1.5): `prerecorded.v2`, `sync.v1`, `streaming.v3`, `DictationTranscriber`, `TextToSpeech`/`TTSSession`, `LLMGateway`. Node SDK with the same surface (`client.tts`, `client.dictation`, streaming).
- CLI `assembly`: `transcribe`, `stream`, `dictate`, `speak`, `agent` (full-duplex terminal voice agent, ~20 voices, `--show-code` prints the equivalent Python), `live` (client-side cascading agent: Streaming STT + deepagents brain on LLM Gateway + streaming TTS, with web search/URL fetch), `llm`, `eval` (WER), `setup` (installs docs MCP server + coding-agent skills), `webhooks listen`, `init/dev/share/deploy`.
- Docs MCP server and Claude Code / Cursor skills (`assembly setup`, `assemblyai-skill`, `docs/agent-instructions.md`, `llms.txt`). The `assemblyai-mcp` server covers async transcription + Speech Understanding only (not TTS/agents).
- Reference agents (MIT): `assemblyai-pipecat-reference-voice-agent` and `assemblyai-livekit-reference-voice-agent`. Both: Universal-3.6 Pro -> LLM Gateway (`gemma-4-31b`) -> AssemblyAI TTS with word timings; one file agent (`src/bot.py` / `src/agent.py`); skills for voice, turn detection, VAD, voice focus, keyterms, languages, medical mode, LLM model, data residency, add-a-tool; Dockerfile; tests; deploy to Pipecat Cloud / LiveKit Cloud or any container host.

---

## 3. LiveKit vs Pipecat (brief)

They occupy the same slot (open-source voice-agent orchestration framework) and are roughly interchangeable for a two-party STT -> LLM -> TTS agent, but they are built around different centres of gravity.

| | LiveKit Agents | Pipecat |
|---|---|---|
| Maintainer / licence | LiveKit, Apache-2.0 (turn-detector model under LiveKit Model License) | Daily, BSD-2 |
| Core abstraction | `AgentSession` joins a WebRTC **room** on a LiveKit server (Cloud or self-hosted). Event-driven, state auto-synced to clients. | A **pipeline** of frame processors (transport -> STT -> LLM -> TTS -> transport). Static graph, you manage state/client sync. |
| Media server | Required: LiveKit SFU. The framework assumes it. | None required. Transports: SmallWebRTC (P2P), Daily, **LiveKit**, FastAPI WebSocket, Vonage, WhatsApp, local; Twilio/Telnyx/Plivo via serializers. |
| Languages | Python and Node | Python (JS client SDKs) |
| Telephony | Native SIP trunking | Via Daily or serializers |
| Multi-party / video / avatars | Strong (rooms, video tracks, avatar providers) | Fine for 2-party; multi-party is more manual |
| Integrations | Plugin per vendor + LiveKit Inference unified layer | Largest catalogue (~24 STT, 26 LLM, 32 TTS in README) |
| Hosting | LiveKit Cloud (`lk agent deploy`) or your container | Pipecat Cloud (`pipecat cloud deploy`) or your container |
| AssemblyAI support | STT + TTS plugins, official reference agent | STT + TTS, official reference agent |

Interchangeable? For your use case, yes: both reference agents implement the identical AssemblyAI pipeline and both expose the same knobs. Choose LiveKit if you want a browser/mobile client with zero client-side plumbing, SIP phone numbers, or more than two participants. Choose Pipecat if you want a dependency-free local loop (SmallWebRTC or plain WebSocket), the most explicit control over the frame pipeline, or to swap vendors frequently. Note the asymmetry: Pipecat can use LiveKit as a transport, but LiveKit Agents cannot run without a LiveKit server.

Neither is a vendor of models; the bill is the models either way.

---

## 4. Recommended architecture for the file-system agent

```
mic/browser ──PCM──> Universal-3.6 Pro Realtime (WebSocket, built-in EOT, prompt = agent's last question)
                       │ Turn (final) events
                       ▼
             agent loop (your process in the container)
               ├─ optional: Dictation-style cleanup prompt via LLM Gateway on each final turn
               ├─ LLM Gateway chat.completions (tools: list_dir, read_file, write_file, grep, run_cmd ...)
               │     tool calls executed against a sandboxed root inside the container
               └─ streams reply tokens
                       │ sentences / tokens
                       ▼
             AssemblyAI-TTS-1 WebSocket session (Generate / Flush / Cancel, word_boundaries=true)
                       │ 24 kHz PCM
                       ▼
                   speaker/browser  (barge-in: on input.speech.started -> TTS Cancel, truncate history to last spoken word)
```

Design notes:
- Sandbox the tool root (e.g. `/workspace`) and allow-list commands; the LLM, not you, decides when to call them.
- Speak the first sentence as soon as the LLM emits it; keep one TTS session for the whole conversation.
- Feed the spoken reply text into the STT session's context/`prompt` to improve recognition of the user's answer.
- Second experiment: the same tool set exposed as Voice Agent API client-side tools (`tool.call` -> `tool.result`) to compare latency and effort against the chained build.
- Optional third input mode: push-to-talk through the Dictation API (`llm_instruction` tuned for commands) to compare cleaned vs verbatim transcripts as agent input.

---

## 5. Sources

AssemblyAI docs/blog (via search snippets): Models; Voice Agent API overview, session configuration, events reference, message sequence, tool calling, client-side tools, connect-your-own-LLM, manage agents, test with Cekura; TTS quickstart, voices, cloned voices, WebSocket API, OpenAI compatibility; Dictation API docs and launch post ("Introducing the Dictation API"), "Dictation cleanup"; LLM Gateway overview/quickstart, "Apply LLM Gateway to Streaming"; Streaming prompting guide; "Universal-3.6 Pro Realtime: your agent can take no for an answer"; "Contextual awareness in Universal-3.5 Pro Realtime"; "Introducing AssemblyAI-TTS-1" (27 Oct 2026); "How to build a voice agent with AssemblyAI: streaming STT, LLM, and TTS" (29 Oct 2026); "Build a voice agent with a chained STT-LLM-TTS architecture"; "Voice agent architectures"; Pipecat and LiveKit intro guides; pricing page; changelog.

GitHub (read directly): AssemblyAI/assemblyai-python-sdk, assemblyai-node-sdk, cli, blurt, assemblyai-pipecat-reference-voice-agent, assemblyai-livekit-reference-voice-agent, voice-agent-starter-python, assemblyai-mcp, voice-standard-bench; pipecat-ai/pipecat; livekit/agents.

Third-party: MarkTechPost (29 Oct 2026) on TTS-1; LiveKit field guide "LiveKit vs Pipecat"; Fora Soft "Pipecat vs LiveKit Agents"; Cekura AssemblyAI pricing round-up; usagepricing.com Dictation API entry; jambonz AssemblyAI voice agent tutorial.
