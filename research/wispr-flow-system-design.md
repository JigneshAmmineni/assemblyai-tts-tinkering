# How Wispr Flow Works Under the Hood: A System-Design Teardown

**Date:** 2026-10-31
**Scope:** Wispr Flow (wisprflow.ai), the closed-source voice dictation app from Wispr Inc. Everything below comes from public sources. Each claim carries one of four confidence labels:

- **[Confirmed]**: stated by Wispr, or by a vendor case study Wispr took part in.
- **[Strongly implied]**: follows directly from primary evidence, including direct reading of reverse-engineered client code.
- **[Third-party]**: a claim by a reviewer, competitor, or analyst that I could not verify against a primary source.
- **[Speculation]**: my own inference.

> **Method note.** In this research environment, direct page fetches to `wisprflow.ai`, `docs.wisprflow.ai`, and `baseten.co` were blocked at the network level. Wispr's and Baseten's primary pages were therefore read through search-engine extracts, not full-page fetches. The one exception is the reverse-engineered `wisprflow-sdk` repository, which I cloned and read in full. Quotes from Wispr pages are as close to verbatim as the extracts allowed. Check exact wording at the linked URLs before quoting it externally.

---

## Executive summary

1. **STT model.** Until September 2026, Wispr never publicly named its speech recognizer. Its stated engineering budget was "<200 ms ASR" on infrastructure hosted by Baseten. On 2026-08-17 Wispr previewed **Canto**, its first in-house speech model, and made it the default for all users around mid-September 2026 **[Confirmed]**. Canto has about 2B parameters and starts from a pretrained speech-text model. Wispr then trains it with supervised fine-tuning (SFT) followed by GRPO reinforcement learning, and the model takes the user's personal vocabulary as runtime context **[Confirmed]**. What powered Flow's speech recognition before Canto (fine-tuned open model, vendor API, or both) is **unknown**.
2. **Cleanup.** Cleanup is a separate LLM post-processing stage on the server. It ran on **fine-tuned Llama models** served on Baseten with TensorRT-LLM **[Confirmed via Baseten case study]**. Computerworld reports **Llama 3.1 plus proprietary models "from the likes of OpenAI"** **[Third-party press]**. Subprocessor lists include OpenAI, Anthropic, and Cerebras as LLM providers **[Third-party]**. Self-corrections ("2, actually 3") are handled by a feature Wispr calls **Backtrack** **[Confirmed]**.
3. **Context.** The server receives a lot of context. Wispr's docs list the app category, textbox contents before, after, and around the cursor, on-screen text read via accessibility APIs, names visible on screen, and variable and file names in IDEs **[Confirmed]**. The reverse-engineered protocol adds the app name, bundle ID, URL, a screenshot field, OCR tokens, a personal dictionary, replacements, snippets, per-app writing style (formal, casual, very casual, excited), and an editing-strength setting **[Strongly implied]**.
4. **Latency.** Wispr's target is **under 700 ms from the end of speech to formatted text**, budgeted as <200 ms ASR, <200 ms LLM, and <200 ms network **[Confirmed]**. Baseten states the target as **p99 < 700 ms**, with the LLM producing **100+ tokens in under 250 ms** **[Confirmed]**. The client opens one **bidirectional gRPC stream** to a Baseten endpoint. It sends preferences and context first, then audio packets *while you speak*, and closes with a "FINAL" commit when you release the key **[Strongly implied]**. Text is inserted once, after release. Speech recognition overlaps with speaking, while the LLM cleanup almost certainly runs on the whole utterance after the FINAL commit **[Strongly implied]**.
5. **Streaming cleanup.** Flow does **not** insert cleaned text incrementally on desktop. The wire protocol does carry partial `raw_text` and `formatted_text` frames, so the server *can* produce provisional formatting, but nothing shows Flow displaying it. Aqua Voice offers both modes: "Instant" inserts ~450 ms after you stop speaking, and "Streaming" shows words live. Google's Gboard "Rambler" is reported to clean up speech as it arrives. Doing cleanup during streaming requires commit/revise semantics, because a self-correction can rewrite text spoken seconds earlier. Research on re-translation "erasure", LocalAgreement, and wait-to-commit disfluency tagging gives workable patterns (Section 5).

---

## 1. STT model: own model or third-party ASR?

### What Wispr has said

- **Before Canto.** In its engineering post "Technical challenges and breakthroughs behind Flow" (around September 2025), Wispr set an end-to-end ASR budget under 200 ms. It also said it was building "context-conditioned ASR models", conditioned on speaker qualities, surrounding context, and individual history ([Wispr: technical challenges](https://wisprflow.ai/post/technical-challenges)) **[Confirmed]**. The post does not say which recognizer was in production.
- **Canto (2026).** Wispr announced Canto alongside its $280M Series B (Menlo Ventures, $2B valuation) on 2026-08-17, describing it as "our first in-house speech model" ([VKTR](https://www.vktr.com/ai-platforms/wispr-hits-2b-valuation-launches-canto-voice-model/); [Wispr Flow on X](https://x.com/WisprFlow/status/2110085776369471596)) **[Confirmed]**. Details from the Canto page ([wisprflow.ai/canto](https://wisprflow.ai/canto)) **[Confirmed]**:
  - Canto starts "from a model pretrained on millions of hours of speech and text". Training then runs in two stages: SFT on audio paired with transcripts, then RL with **GRPO**, where several candidate transcripts are sampled per clip and each complete output is scored.
  - It takes the user's **personal vocabulary as runtime context**. Wispr trains with *distractor* vocabulary terms mixed with true ones so the model learns "when context deserves to be followed", not just to copy the list.
  - It is described as the first model from "Wispr Advanced Interfaces Lab". A unified transcription-plus-diarization architecture is on the roadmap.
  - Wispr says Canto had "the lowest WER" among the real-time models it evaluated. One summary says the comparison included Google, OpenAI, AssemblyAI, and Deepgram models ([Releasebot summary](https://releasebot.io/updates/wispr-flow); [BenchLM](https://benchlm.ai/models/wispr-canto)) **[Third-party summary of a Wispr claim]**.
  - Reported numbers: about 2B parameters. WER in hard acoustic conditions falls from over 30% to roughly 5–10%. The share of dictations that need manual edits falls by 30–35% ([VKTR](https://www.vktr.com/ai-platforms/wispr-hits-2b-valuation-launches-canto-voice-model/); [Pulse 2.0](https://pulse2.com/wispr-raises-280-million-at-2-billion-valuation-as-revenue-grows-150-quarterly-and-voice-ai-push-accelerates/)). A post attributed to CEO Tanay Kothari cites **3.4% WER on 10 hours of real Flow dictations from more than 2,300 speakers** ([X/@tankots](https://x.com/tankots/status/2100680985423843608)). Wispr did not publish test languages or the comparison models in full, and there is no independent benchmark **[Confirmed as claim; unverified]**.
  - Canto became the default for everyone around 2026-09-17 ([Wispr What's new](https://wisprflow.ai/whats-new); [BenchLM](https://benchlm.ai/models/wispr-canto)) **[Confirmed / Third-party date]**.
- **Why they built it.** Press coverage says the founders judged general-purpose models such as Whisper "good but not great". The problems cited were hallucinated words, weak handling of accents and code-switching, and no adaptation to the user ([Pulse 2.0](https://pulse2.com/wispr-raises-280-million-at-2-billion-valuation-as-revenue-grows-150-quarterly-and-voice-ai-push-accelerates/amp/)) **[Third-party press quoting Wispr]**. CTO Sahaj Garg's LinkedIn profile says a "deep personalization stack" has to be built into the speech model itself ([LinkedIn](https://www.linkedin.com/in/sahajgarg/)).
- **Multilingual.** Wispr's research post on supporting 100 languages describes **per-language engine selection**, which it says more than halves error rates in internal tests. The post notes that standard models do poorly on Hindi, Marathi, Thai, and Tamil, and discusses romanized-Hindi output for Hinglish ([Wispr research: supporting languages](https://wisprflow.ai/research/supporting-languages)) **[Confirmed]**. "Engine selection" strongly implies that, at least before Canto, **several ASR backends were routed per language**, some of which were probably third-party **[Strongly implied / Speculation on the vendors]**.

### Hosting and vendors

- Baseten hosts Wispr's models. The reverse-engineered client opens its gRPC stream to `model-<id>.grpc.api.baseten.co`, using the service `flow_api.v1.TranscriptionService/TranscribeStream` ([wisprflow-sdk TECHNICAL_DETAILS.md](https://github.com/ThisisShashwat/wisprflow-sdk)) **[Strongly implied]**. A single Baseten-hosted service carrying both `raw_text` and `formatted_text` fits a Baseten **Chains** pipeline (ASR step → LLM step), which Baseten's case study names ([Baseten case study](https://www.baseten.co/resources/customers/wispr-flow/)).
- Subprocessors reported by third parties include Baseten, OpenAI, Anthropic, Cerebras, and AWS us-east-1 ([Voibe](https://www.getvoibe.com/resources/wisprtype-vs-wispr-flow/)). A stricter audit says DPA Annex 2 lists 34 entities, including Fireworks AI, Google, OpenPipe, Modal Labs, and ElevenLabs. The same audit says the public Trust Center list changed between snapshots, from 24 to 29 entities, and later moved behind an NDA ([Routines audit](https://getroutines.ai/transparency/wispr-flow)) **[Third-party]**. **Groq does not appear in any source** I found.
- **Before Canto: unknown.** No primary source names Whisper, Deepgram, AssemblyAI, Google, or ElevenLabs as Flow's recognizer. Comparison sites say outright that Wispr "does not publicly disclose" the model ([Voibe](https://www.getvoibe.com/resources/openai-whisper-vs-wispr-flow/)). One explainer claims GPT-Transcribe and Whisper-large-v3-turbo ([Forasoft](https://www.forasoft.com/learn/ai-for-video-engineering/articles-ai/whisper-flow-app-engineering-walkthrough)), but I could not corroborate it **[Third-party, low confidence]**. Several signals point to a mix of self-hosted fine-tuned open models on Baseten and vendor APIs as fallbacks or for some languages: the ElevenLabs, Google, and OpenAI subprocessors, the per-language "engine selection" language, and the job posts about "personalization of our speech models … with fine-tuning and RL" ([Ashby job post](https://jobs.ashbyhq.com/wispr-flow/9cf022b6-55b1-4fcc-940a-6988bd94b6d3)) **[Speculation]**.

**Answer:** Today, Wispr runs its own model (Canto) **[Confirmed]**. Before September 2026, the recognizer was never disclosed and was probably a routed mix **[Speculation]**.

---

## 2. Cleanup of disfluent, self-corrected speech

### Architecture

- Cleanup is a **separate LLM stage after ASR**. Baseten: "Sahaj and his team chose Llama … as the base for their real-time transcript cleanup step", "fine-tuned these LLMs to precisely solve user tasks based on the users' context and preferences", served with Baseten's TensorRT-LLM engine builder and Chains ([Baseten](https://www.baseten.co/resources/customers/wispr-flow/)) **[Confirmed]**.
- Computerworld: "For text editing, it uses the open-source Llama 3.1 model, combined with proprietary models from the likes of OpenAI" ([Computerworld](https://www.computerworld.com/article/4107331/wispr-ceo-interview-post-keyboard-office.html)) **[Third-party press]**. The same piece quotes Wispr describing "voice-first models" trained to learn transcription, formatting, and intent together, "rather than bolting speech recognition onto a general-purpose language model". That reads as a direction of travel, not a description of the shipped stack.
- **The wire protocol confirms the two-stage split.** Server frames carry a `State` message with `raw_text` (ASR) and `formatted_text`, plus a `Result` with `result_html`, `result_plaintext`, and a status (`FORMATTED`, `ERROR`, or `RAW_TRANSCRIPT`). A `disable-formatting` gRPC header exists, so the LLM pass can be skipped, and the client falls back to raw text if formatting fails ([wisprflow-sdk](https://github.com/ThisisShashwat/wisprflow-sdk)) **[Strongly implied]**.
- **Controls the client sends to the formatter** ([wisprflow-sdk](https://github.com/ThisisShashwat/wisprflow-sdk)) **[Strongly implied]**:
  - `WRITING_STYLE` ∈ {FORMAL, CASUAL, VERY_CASUAL, EXCITED}, configured **per app type** (personal, work, email, other)
  - `EDITING_STRENGTH` ∈ {VERBATIM, LIGHT, MEDIUM, HEAVY}
  - `APP_TYPE` ∈ {other, browser, personal, work, email, chatbot, developer}
  - email signature settings
  - a personal dictionary, starred terms, replacements, and snippets

  These are essentially the LLM's conditioning variables.
- **Command mode** (for example, "make this more formal" over selected text) uses a **separate REST call**: `POST api.wisprflow.ai/llm/command_mode_route` with `selected_text`, `instruction`, and style settings ([wisprflow-sdk](https://github.com/ThisisShashwat/wisprflow-sdk)) **[Strongly implied]**.

### Self-correction ("Backtrack"), fillers, formatting

- Wispr's help doc "How do I use Smart Formatting & Backtrack" covers both features ([docs.wisprflow.ai](https://docs.wisprflow.ai/articles/5373093536-how-do-i-use-smart-formatting-and-backtrack)) **[Confirmed]**:
  - Backtrack removes filler words, false starts, and *clear* self-corrections.
  - Cue words include "actually", "scratch that", and "never mind", but restating your intent also works.
  - Non-corrective uses are kept ("I actually enjoyed the movie").
  - Example: "Let's do coffee at 2 actually 3" → "Let's do coffee at 3".
  - The original dictation is kept in Recent Activity.
  - Smart Formatting (lists, punctuation, structure) is a separate toggle, and it "does not correct misheard words".

  This describes semantic rewriting by an LLM, not rule-based deletion **[Strongly implied]**.
- **Learning from edits.** "Flow's formatter learns from real user edits (punctuation, spacing, and grammar corrections)" ([Wispr research](https://wisprflow.ai/research/supporting-languages)). The engineering post treats user corrections as the key signal, with a goal of driving them to zero ([Wispr](https://wisprflow.ai/post/technical-challenges)) **[Confirmed]**. Job posts mention "fine-tuning and RL / DPO" for personalization ([startup.jobs listing](https://startup.jobs/ml-engineer-wispr-ai-6425827)). Garg's SE Radio episode on ambiguity talks about learning "revealed preferences" from behavior without explicit feedback ([SE Radio 715](https://se-radio.net/2026/04/se-radio-715-sahaj-garg-on-designing-for-ambiguity-in-human-input/)) **[Confirmed in outline]**. OpenPipe, a fine-tuning and RL platform, appearing in the DPA annex fits this picture **[Third-party / Speculation]**.
- **Not disclosed:** the prompt format, whether there is one model per style or per app, model sizes (Baseten's "100+ tokens in <250 ms" fits an 8B-class model on H100s with TensorRT-LLM **[Speculation]**), and when OpenAI, Anthropic, or Cerebras models are used instead of Llama. Plausible uses are command mode, long dictations, and fallback **[Speculation]**.

---

## 3. Context awareness

### What the product docs say

From Wispr's "Context Awareness" help article ([docs.wisprflow.ai](https://docs.wisprflow.ai/articles/4678293671-feature-context-awareness)) **[Confirmed]**:

- Flow reads text near the cursor.
- It classifies the active app as Email, Work messaging, Personal messaging, or Other.
- It uses names visible on screen, such as email recipients, to spell proper nouns correctly.
- Context can include app information, textbox contents (before, selected, and after the cursor), on-screen text, variable and file names in coding apps, and your user identifier within the app.
- It "works from text and does not take screenshots".
- It requires macOS Accessibility permission.
- On Android, Accessibility lets Flow read on-screen text, field layout, and app or website names. Flow skips password and credit-card fields, banking apps, and password managers ([Android setup doc](https://docs.wisprflow.ai/articles/8858845757-setup-wispr-flow-on-android-android-settings)).

Per-app tone ("Styles": formal in email, casual in personal chat) is a documented feature. It matches the `styleConfig` keyed by app type in the protocol.

### What the privacy policy says

The policy's "Customer Content" section covers audio inputs, meeting data, and "contextual information you choose to provide". If Context Awareness is enabled, Wispr "may collect limited content from the app in use, such as on-screen text, to improve output accuracy" ([Wispr privacy policy](https://wisprflow.ai/privacy-policy), as extracted via search) **[Confirmed]**. A critical analysis of the version updated 2026-07-25 says the policy names "the application used for dictation" but contains none of the words keystroke, keyboard, typing, URL, or browsing ([Voibe](https://www.getvoibe.com/resources/is-wispr-flow-safe/)) **[Third-party]**. Wispr's Data Controls page says usage statistics such as word counts are collected regardless of settings ([wisprflow.ai/data-controls](https://wisprflow.ai/data-controls)). Third parties report that training on user data is opt-in or off for Enterprise and HIPAA accounts, with a zero-retention "Privacy Mode" ([Voibe](https://www.getvoibe.com/resources/is-wispr-flow-safe/)) **[Third-party]**.

### What the client actually sends (reverse-engineered)

The `ContextRequest` message in the gRPC stream contains the following fields ([wisprflow-sdk](https://github.com/ThisisShashwat/wisprflow-sdk)) **[Strongly implied]**:

- **Textbox:** `before_text`, `after_text`, `selected_text`, `textbox_contents`
- **Screen:** `content_text`, `content_html`, and a `screenshot` bytes field
- **App:** `app_name`, `bundle_id`, `url`, `session_apps`
- **Dynamic vocabulary:** `screen_ax` (accessibility-tree tokens), `screen_ocr` (OCR tokens), `variable_names`, and `file_names`, each capped at 50 items

The `InitRequest` carries the user profile (name, email), languages, personal dictionary, replacements, snippets, and style preferences.

Independent analyses add more detail:

- One write-up says the app walks the accessibility tree up to 214 elements and 9 levels deep. It says Flow streams **OPUS** audio over gRPC to Baseten along with accessibility text, app names, URLs, and extracted proper nouns. It also says a local `flow.sqlite` stores audio, transcripts, and textbox contents ([Wensen Wu](https://www.wensenwu.com/thoughts/wispr-flow-investigation)) **[Third-party]**.
- A 2025 incident showed active-window screenshots being uploaded as part of Context Awareness. A Reddit user who reported it was banned, after which CTO Sahaj Garg apologized and Context Awareness was reworked with explicit toggles ([Embertype](https://embertype.com/blog/the-day-wispr-flow-banned-a-user/); [ModelPiper](https://modelpiper.com/blog/wispr-flow-privacy-incident); [Kintal](https://kintal.co/thinking/what-wispr-flow-actually-does)) **[Third-party; dates conflict across sources]**.
- Voibe reports a separate "Screen OCR" control ([Voibe](https://www.getvoibe.com/resources/is-wispr-flow-safe/)) **[Third-party]**.

The `screenshot` and `screen_ocr` fields in the protocol mean pixel-derived context is at least supported. That sits uneasily with the doc's "does not take screenshots" line, unless screenshots are OCR'd on the device or the feature is off by default **[Strongly implied / unresolved]**.

### How the context is used

There are two channels. **ASR biasing**: Canto takes personal vocabulary at runtime, and the "dynamic vocabulary" scraped from the screen is almost certainly fed as bias terms **[Confirmed / Strongly implied]**. **LLM conditioning**: textbox before and after text for continuity and capitalization, app type for style, and recipient names for spelling **[Strongly implied]**. The engineering post says "most personalization data must live on a user's device", so the client chooses what to send each time ([Wispr](https://wisprflow.ai/post/technical-challenges)) **[Confirmed]**. Prior dictations are not shown to be sent per request, though the local database keeps them **[Unknown]**.

---

## 4. Latency

### Published numbers

| Metric | Value | Source | Label |
|---|---|---|---|
| End of speech → formatted text | < 700 ms | [Wispr](https://wisprflow.ai/post/technical-challenges) | Confirmed |
| Budget split | ASR < 200 ms, LLM < 200 ms, network < 200 ms "from anywhere… with spotty internet" | [Wispr](https://wisprflow.ai/post/technical-challenges) | Confirmed |
| Percentile | p99 (per-user p90/p99 tracked) | [Baseten](https://www.baseten.co/resources/customers/wispr-flow/) | Confirmed |
| LLM throughput requirement | 100+ tokens processed and generated in < 250 ms | [Baseten](https://www.baseten.co/resources/customers/wispr-flow/); Garg on [SE Radio 703](https://se-radio.net/2026/01/se-radio-703-sahaj-garg-on-low-latency-ai/) ("50 or 100 words within 250 ms") | Confirmed |
| LLM infra target in hiring | "<500 ms LLM inference for millions of requests from everywhere" | [Ashby](https://jobs.ashbyhq.com/wispr-flow/9cf022b6-55b1-4fcc-940a-6988bd94b6d3) | Confirmed |
| Improvements | Android launch with an "infrastructure rewrite" 30% faster (Feb 2026); median latency −14% (Oct 2026) | [press](https://steamdeveloper.pages.dev/2026/02/23/wispr-flow-launches-an-android-app-for-ai-powered-dictation/); [Wispr on X](https://x.com/WisprFlow/status/2110085776369471596) | Confirmed / Third-party |
| Observed by reviewers | ~0.5–2 s; competitor Willow claims Flow at 400–900 ms | [Spokenly](https://spokenly.app/blog/wispr-flow-review); [Willow](https://willowvoice.com/blog/wispr-flow-whisper-flow-willow-comparison) | Third-party (competitor) |
| Speed marketing | ~220 wpm vs 45 typing ("4×") | [Chatgate summary](https://chatgate.ai/post/wispr-flow) | Marketing |

### How the pipeline hides latency (from the protocol)

The reverse-engineered client opens a **bidirectional gRPC stream** to a Baseten endpoint. It sends messages in this order ([wisprflow-sdk](https://github.com/ThisisShashwat/wisprflow-sdk)) **[Strongly implied]**:

1. `InitRequest` (user, preferences, vocabulary, style), then `Commit(NON_FINAL)`.
2. `ContextRequest` (app, textbox, screen, dynamic vocabulary), then `Commit(NON_FINAL)`.
3. **Audio packets streamed while the user speaks**, each with `Commit(NON_FINAL)`.
4. The last packet, with `Commit(FINAL)`, which corresponds to key release.

The server streams back frames with the latest `raw_text` and `formatted_text`, plus heartbeats. Two more details: a `GET api.wisprflow.ai/warmup` is sent before the stream to avoid cold starts, and the client retries once after 500 ms on UNAVAILABLE or DEADLINE_EXCEEDED. Another static analysis describes the transport as gRPC first, with WebSocket and HTTPS fallbacks, and mentions Modal-hosted endpoints ([shepetal PR #6](https://github.com/backant-io/shepetal/pull/6)) **[Third-party]**.

What follows from this design:

- **Context and preferences arrive before the audio ends**, so prompt assembly, retrieval, and prefill of the stable part of the LLM prompt can happen before release **[Speculation on prefill reuse]**.
- **Audio upload and probably incremental ASR overlap with speech.** At release, only the tail of the audio still needs decoding. That makes "<200 ms ASR after end of speech" achievable for long dictations **[Strongly implied]**.
- **The LLM runs after FINAL on the whole utterance.** The 700 ms budget is measured from the end of speech. "Generate 100+ tokens in <250 ms" describes rewriting a full paragraph at once, not incremental tokens **[Strongly implied]**.
- **Insertion is one-shot after release.** On the desktop, a Swift helper pastes via the clipboard or injects text ([BoringNotch issue](https://github.com/lionel509/boring.notch/issues/3); [shepetal PR #6](https://github.com/backant-io/shepetal/pull/6)). An Android reviewer saw no live transcript, just text "within a second" of tapping done ([Beebom](https://beebom.com/wispr-flow-ai-dictation-app-transcribes-voice-faster-than-typing)) **[Third-party]**.
- **On-device components** are the client shell, key hooks, the accessibility-tree walk, possibly OCR, audio encoding (OPUS), and local replacements and snippets. The SDK also applies replacements locally after the gRPC result. **No on-device ASR or LLM**: Flow does not work offline ([SpeakOFlow](https://www.speakoflow.com/blog/does-wispr-flow-work-offline)) **[Third-party, consistent with protocol]**.
- **Inference providers:** Baseten (TensorRT-LLM, Chains, multi-region) is the confirmed primary. Cerebras, Fireworks, OpenAI, and Anthropic appear as subprocessors and may serve fast or fallback LLM paths **[Third-party / Speculation]**. The September 2024 launch release credits an "ultra-fast inference engine" with no detail ([BusinessWire](https://www.businesswire.com/news/home/20240930079034/en)).

---

## 5. Can cleanup run while streaming?

### What Flow does

Flow streams **audio** and probably **ASR**, but it commits **cleaned text only once, after release** **[Strongly implied]**. The protocol can return provisional `formatted_text` frames before FINAL, and the SDK exposes them as partial callbacks. Whether the server actually runs the LLM speculatively on partial audio is not documented **[Unknown]**. Flow's product choice avoids the hard problem: it never has to retract text it has already inserted into someone else's text field, where undo and rewrite are fragile across apps.

### What competitors do

- **Aqua Voice** has two modes ([aquavoice.com/llms.txt](https://aquavoice.com/llms.txt)) **[Confirmed]**:
  - "Instant Mode: text appears ~450 ms after you stop speaking."
  - "Streaming Mode: words appear in real time as you talk", which Aqua says gives "maximum contextual understanding and precise control over text and formatting".

  Aqua's 2024 Launch HN described a voice-native editor running "six models" together to transcribe, interpret, and rewrite the document live ([Launch HN](https://news.ycombinator.com/item?id=39828686)). Its own ASR model, **Avalon**, is evaluated on getting key terms right (AISpeak), not raw WER ([Aqua: Introducing Avalon](https://aquavoice.com/blog/introducing-avalon)). The client-side "Deep Context" reads on-screen content. Aqua owns its editor surface (or a preview overlay), which is what makes live revision feasible.
- **Willow Voice** publishes only marketing numbers (about 200 ms average latency, a 95% zero-edit rate) and no architecture ([Willow blog](https://willowvoice.com/blog/automatic-punctuation-dictation)) **[Third-party/vendor]**.
- **Google Gboard "Rambler"** (Gemini, announced May 2026) removes fillers and self-corrections. In the "3 p.m., actually 2 p.m." example, it outputs only the corrected time. Coverage describes it as processing speech "as it arrives" ([9to5Google](https://9to5google.com/2026/05/12/gemini-intelligence-announcement/); [Gadget Hacks](https://android.gadgethacks.com/news/gboard-rambler-voice-typing-upgrade-explained-new-vs-existing-features/)) **[Third-party]**.
- **Superwhisper** runs batch ASR (local Whisper, Groq, or Deepgram) and then an optional user-defined LLM "mode". Its plain transcription mode skips the LLM to be fastest ([Superwhisper docs](https://superwhisper.com/docs/modes/built-in.md)).

### Research and prior art

- **Streaming disfluency detection.** "Teaching BERT to Wait" trains a streaming tagger that decides whether to label a token now or wait for more context. It comes within about 1 F1 of non-streaming models, with less flicker and an average extra wait of about 0.21 tokens ([arXiv 2205.00620](https://arxiv.org/abs/2205.00620)). "Streaming Joint Speech Recognition and Disfluency Detection" does the tagging inside a blockwise streaming ASR model, with lower latency and a smaller model than a cascade ([arXiv 2211.08726](https://arxiv.org/pdf/2211.08726)).
- **LLM disfluency removal.** The DRES benchmark finds that segmenting transcripts helps, that reasoning models **over-delete** fluent tokens, and that fine-tuning trades generalization for precision ([arXiv 2509.20321](https://arxiv.org/abs/2509.20321v1)). "Mind the Pause" (ACL 2026) puts a disfluency tagger in front of an instruction-tuned LLM rewriter ([arXiv 2605.12242](https://arxiv.org/pdf/2605.12242)). That tagger-guides-rewriter split is a natural fit for streaming.
- **Commit/revise theory from simultaneous translation.** Re-translation re-runs the model on each growing prefix and measures flicker as **erasure**, the number of tokens deleted from the previous output. Biased beam search toward the previous output and **masking the last k words** trade flicker for latency. Re-translation with normalized erasure below 0.2 matches streaming MT, and zero erasure reduces to wait-k ([arXiv 1912.03393](https://arxiv.org/pdf/1912.03393); [arXiv 2004.03643](https://arxiv.org/pdf/2004.03643)).
- **LocalAgreement** (used in Whisper-Streaming) commits only the prefix on which two consecutive hypotheses agree ([arXiv 2307.14743](https://arxiv.org/html/2307.14743)). The same policy applies unchanged to an LLM cleanup stage.

### The core difficulty and tradeoffs

A self-correction is a **non-local edit**. "Send it Tuesday, no wait, Wednesday" changes a token roughly 1.5 s back, and "scratch that" can delete a whole sentence. An incremental cleaner therefore needs one of three things:

- **(a) A hold-back window.** Commit cleaned text only up to a stable boundary, such as the end of a clause or a pause over 300 ms, and keep the last N words provisional. This adds a fixed delay and fails on corrections that reach past the window.
- **(b) Revision of committed text.** Fine in your own UI. Risky inside third-party text fields, and visually distracting, with the same flicker problem as re-translation.
- **(c) Speculative cleanup plus a final pass.** Clean prefixes continuously in the background, but insert only after release, re-running the LLM over just the unstable tail plus a summary or KV cache of the already-clean prefix. This cuts post-release LLM time without any visible revisions.

My read: Flow's design (one-shot insert after release, a strict 250 ms LLM budget) is the simple, robust end of this spectrum. Its per-utterance cost grows with dictation length, which is why it needs very fast LLM decoding **[Speculation]**.

---

## 6. Reverse engineering and open-source clones

### Wispr Flow internals (community findings)

- **Client stack.** On macOS and Windows the client is an **Electron** app (`resources/app.asar`). On macOS it also has a **native Swift helper** that "owns every OS-level signal": the global key listener, text injection, accessibility, and audio. The two talk over stdio IPC. A Reddit roundup summarizes the dictation flow as "Electron app, Swift helper over stdio, clipboard paste" ([shepetal PR #6](https://github.com/backant-io/shepetal/pull/6), static analysis of v1.6.1174; [soravo_electron PR #41](https://github.com/eySRbS4zgHuW3gMFZB2/soravo_electron/pull/41), Windows v1.6.1337; [BoringNotch issue #3](https://github.com/lionel509/boring.notch/issues/3)) **[Third-party, consistent across three independent analyses]**. More than 10 processes run, including separate keyboard-listener and text-injector binaries ([Wensen Wu](https://www.wensenwu.com/thoughts/wispr-flow-investigation)).
- **Auth.** Supabase JWTs are stored in the app's `session.json` ([wisprflow-sdk](https://github.com/ThisisShashwat/wisprflow-sdk)) **[Strongly implied]**.
- **Transport and protocol.** Covered in Sections 3 and 4: bidirectional gRPC `flow_api.v1.TranscriptionService/TranscribeStream` on Baseten, with Init/Context/Audio messages and NON_FINAL/FINAL commits. The SDK patch hooks a JS function named `getDesiredGrpcModelInfo()`, which suggests the **client picks a model or deployment ID dynamically**, for example per language or A/B arm. REST under `api.wisprflow.ai` handles warmup and command mode ([wisprflow-sdk TECHNICAL_DETAILS.md](https://github.com/ThisisShashwat/wisprflow-sdk)) **[Strongly implied]**.
- **Gaps.** No public analysis from a traffic-interception proxy (such as mitmproxy) names the LLM behind the Baseten endpoint. The model is server-side and invisible to the client. Pieter Levels noted Flow clones appearing ([levels.io](https://levels.io/wispr-flow-granola-whoop-reverse-engineered)), but that post has no technical detail. I found **no Hacker News thread** with a technical teardown.

### Open-source clones and their common pattern

| Project | Shell | ASR | Cleanup | Context |
|---|---|---|---|---|
| [OpenWhispr](https://openwhispr.com/compare/wisprflow) | Electron + React | whisper.cpp, sherpa-onnx (Parakeet), cloud options | llama.cpp local or cloud LLM | — |
| [Handy](https://github.com/cjpais/Handy) | Tauri (Rust + React) | whisper-rs, Parakeet | none or minimal | — |
| [VoiceInk](https://tryvoiceink.com/docs/contextual-awareness) | Native Swift | whisper.cpp, Parakeet (FluidAudio), Apple Speech | "AI Enhancement" via a cloud or Ollama LLM | clipboard + screenshot→OCR text |
| [shepetal](https://github.com/backant-io/shepetal) | macOS, hold-fn | on-device | — | written explicitly for parity with Flow |
| Murmure, FreeFlow, FluidVoice ([overview](https://openalternative.co/alternatives/wisprflow)) | various | Parakeet or Whisper | optional Ollama | — |

The shared design: **push-to-talk → buffer audio → batch ASR on release → optional LLM rewrite prompt (with app or screen context) → paste via clipboard or synthetic keystrokes**. None of these clones implements streaming cleanup. Flow differs from them in four ways: server-side streaming upload, context sent before the audio ends, fine-tuned and personalized models, and a tightly engineered p99.

---

## 7. Applying this to a real-time STT → LLM → TTS voice agent

In a voice agent, the cleaned transcript is consumed by an LLM rather than shown to a person. That changes the tradeoffs: flicker costs nothing (nobody sees it), but **tool calls and side effects must never fire on uncorrected intent**.

### Option A: No explicit cleanup; the agent LLM reads raw streaming text
- Stream partial or final ASR text straight into the agent LLM, with a system prompt saying to resolve self-repairs ("no wait", "actually") using the latest intent.
- **Latency added: 0 ms.** Frontier and mid-size LLMs already handle disfluency well. DRES shows the risk is *over-deletion*, not under-deletion.
- **Use when** the agent model is strong and the transcript is not shown to the user or stored.

### Option B: Incremental cleanup on a stable prefix (LocalAgreement-style)
- Run a small, fast cleaner (a fine-tuned 1–8B model, or a tagger plus rewriter as in "Mind the Pause") on ASR segments once they **stabilize**: immutable finals, or two-hypothesis agreement at clause boundaries.
- Hold back the last clause, or about 1–2 s, because corrections usually point back only a few words.
- At end of turn, only the **tail** still needs cleaning. **Added latency ≈ cleaning one clause (~30–80 ms on fast inference)** instead of a whole paragraph **[Speculation on numbers]**.
- A rare long-range correction ("scratch all that") triggers a full re-clean of the turn, accepting a one-off latency hit.

### Option C: Speculative end-of-turn plus preemptive generation
- On an *eager* end-of-turn signal (for example, Deepgram Flux `EagerEndOfTurn` / LiveKit "preemptive generation"), start cleanup **and** the agent LLM speculatively. If the final transcript matches, adopt the result. Otherwise discard and restart ([LiveKit docs](https://docs.livekit.io/reference/agents-js/classes/plugins_agents_plugin_deepgram.STTv2.html); [LiveKit issue](https://github.com/livekit/agents/issues/5536)).
- **Saves roughly the endpointing wait (200–500 ms)**. The cost is wasted compute on false triggers. Pair it with Option B so the speculative pass is short.
- Gate **TTS audio playback and tool execution** on confirmation, not just generation. Generating early is cheap. Speaking or acting early is not.

### Option D: Fold cleanup into the agent's first tokens
- Ask the agent LLM to emit a short `<intent>` (normalized user request) before its reply. TTS starts only on the reply tokens. This removes a network hop (~50–150 ms) and a second prompt prefill, at the cost of a few extra output tokens.

### Option E: Push context into the ASR, the way Flow and Canto do
- The cheapest accuracy gain is **biasing ASR with dynamic vocabulary**: contact names, product terms, entities from the conversation so far. Most streaming STT APIs offer keyterm or vocabulary prompting (for example, AssemblyAI streaming keyterms; check current docs). Canto's "distractor" training explains why this works best with a curated short list rather than everything in the context.
- Send **session context at connection start** (Flow sends Init and Context before audio), so nothing context-related lands on the end-of-turn critical path.

### Option F: Keep cleanup off the critical path entirely
- For transcripts, CRM notes, or display, run Flow-style full-utterance cleanup **asynchronously after the turn**, while the agent responds from the raw text (Option A).

### Latency budget sketch (end of user speech → first TTS audio)

| Stage | Flow-style batch cleanup | Streaming B+C |
|---|---|---|
| Endpointing | 300–700 ms (silence timeout) | 100–300 ms (eager EOT, speculative) |
| ASR finalize | ~100–200 ms | ~50–150 ms (streaming, tail only) |
| Cleanup LLM | 150–250 ms (whole utterance) | 0–80 ms (tail only, or folded into the agent, Option D) |
| Agent LLM TTFT | 150–400 ms | 150–400 ms (may already be running speculatively) |
| TTS TTFB | 75–200 ms | 75–200 ms |
| **Total** | **~0.8–1.75 s** | **~0.4–1.1 s** |

*(Numbers are illustrative engineering estimates, not measurements **[Speculation]**.)*

**Takeaways for a cascade:**
1. Stream audio and context early, as Flow does.
2. Clean a stable prefix incrementally with a hold-back window.
3. Speculate at end of turn, but gate tool calls and TTS playback on the confirmed transcript.
4. Prefer folding normalization into the agent LLM over adding a separate model hop, unless a person sees the cleaned text.

---

## What is confirmed vs inferred

| Claim | Status | Key source |
|---|---|---|
| End-to-end target < 700 ms after end of speech; 200/200/200 ms budget | Confirmed (Wispr) | [Wispr post](https://wisprflow.ai/post/technical-challenges) |
| p99 target; LLM must do 100+ tokens in < 250 ms | Confirmed (Baseten case study) | [Baseten](https://www.baseten.co/resources/customers/wispr-flow/) |
| Cleanup LLM = fine-tuned Llama on Baseten (TensorRT-LLM, Chains) | Confirmed (Baseten case study) | [Baseten](https://www.baseten.co/resources/customers/wispr-flow/) |
| Llama 3.1 + OpenAI proprietary models for editing | Third-party press | [Computerworld](https://www.computerworld.com/article/4107331/wispr-ceo-interview-post-keyboard-office.html) |
| OpenAI / Anthropic / Cerebras / Fireworks / Google / ElevenLabs / OpenPipe / Modal as subprocessors | Third-party | [Routines](https://getroutines.ai/transparency/wispr-flow), [Voibe](https://www.getvoibe.com/resources/wisprtype-vs-wispr-flow/) |
| Canto: in-house, ~2B params, SFT + GRPO, runtime vocab context, default since ~Sept 2026 | Confirmed (Wispr) | [Canto](https://wisprflow.ai/canto) |
| ASR before Canto | **Unknown**; routed mix is speculation | — |
| Backtrack removes fillers and clear self-corrections | Confirmed | [Docs](https://docs.wisprflow.ai/articles/5373093536-how-do-i-use-smart-formatting-and-backtrack) |
| Context: app category, textbox before/after/selection, on-screen text, names, IDE identifiers | Confirmed | [Docs](https://docs.wisprflow.ai/articles/4678293671-feature-context-awareness) |
| Protocol carries URL, bundle ID, screenshot field, OCR and AX tokens, style and editing-strength enums | Strongly implied (client code) | [wisprflow-sdk](https://github.com/ThisisShashwat/wisprflow-sdk) |
| Bidirectional gRPC; audio streamed during speech; FINAL commit on release | Strongly implied | [wisprflow-sdk](https://github.com/ThisisShashwat/wisprflow-sdk) |
| LLM cleanup runs once on the full utterance after release | Strongly implied | budget wording + protocol |
| Electron + Swift helper; clipboard or injection insertion | Third-party (three analyses agree) | [shepetal](https://github.com/backant-io/shepetal/pull/6), [soravo](https://github.com/eySRbS4zgHuW3gMFZB2/soravo_electron/pull/41) |
| Screenshots uploaded in 2025; CTO apology | Third-party | [Embertype](https://embertype.com/blog/the-day-wispr-flow-banned-a-user/), [ModelPiper](https://modelpiper.com/blog/wispr-flow-privacy-incident) |
| Groq used | **No evidence** | — |
| Streaming (incremental) cleanup shown to the user | **No evidence**; the protocol allows partial formatted frames | — |
| Specific model sizes, prompts, and routing between Llama and OpenAI/Anthropic | **Not public** | — |

---

## Sources

**Wispr primary**
- https://wisprflow.ai/post/technical-challenges
- https://wisprflow.ai/canto
- https://wisprflow.ai/research/supporting-languages
- https://wisprflow.ai/whats-new
- https://wisprflow.ai/privacy-policy
- https://wisprflow.ai/data-controls
- https://wisprflow.ai/lab
- https://docs.wisprflow.ai/articles/4678293671-feature-context-awareness
- https://docs.wisprflow.ai/articles/5373093536-how-do-i-use-smart-formatting-and-backtrack
- https://docs.wisprflow.ai/articles/8858845757-setup-wispr-flow-on-android-android-settings
- https://docs.wisprflow.ai/articles/4497184932-notetaker-privacy-and-security-overview
- https://x.com/WisprFlow/status/2110085776369471596
- https://x.com/tankots/status/2100680985423843608
- https://jobs.ashbyhq.com/wispr-flow/9cf022b6-55b1-4fcc-940a-6988bd94b6d3
- https://startup.jobs/ml-engineer-wispr-ai-6425827
- https://www.linkedin.com/in/sahajgarg/

**Vendor, press, and interviews**
- https://www.baseten.co/resources/customers/wispr-flow/
- https://www.computerworld.com/article/4107331/wispr-ceo-interview-post-keyboard-office.html
- https://se-radio.net/2026/01/se-radio-703-sahaj-garg-on-low-latency-ai/
- https://se-radio.net/2026/04/se-radio-715-sahaj-garg-on-designing-for-ambiguity-in-human-input/
- https://linearb.io/dev-interrupted/podcast/wispr-keyboard-bottleneck-vibe-coding-sahaj-garg
- https://techcrunch.com/2025/06/24/wispr-flow-raises-30m-from-menlo-ventures-for-its-ai-powered-dictation-app/
- https://www.businesswire.com/news/home/20240930079034/en
- https://www.vktr.com/ai-platforms/wispr-hits-2b-valuation-launches-canto-voice-model/
- https://pulse2.com/wispr-raises-280-million-at-2-billion-valuation-as-revenue-grows-150-quarterly-and-voice-ai-push-accelerates/
- https://pulse2.com/wispr-raises-280-million-at-2-billion-valuation-as-revenue-grows-150-quarterly-and-voice-ai-push-accelerates/amp/
- https://steamdeveloper.pages.dev/2026/02/23/wispr-flow-launches-an-android-app-for-ai-powered-dictation/
- https://releasebot.io/updates/wispr-flow
- https://benchlm.ai/models/wispr-canto

**Reverse engineering and privacy analyses**
- https://github.com/ThisisShashwat/wisprflow-sdk (read in full: README, TECHNICAL_DETAILS.md, `_core.py`; last commit 2026-06-09)
- https://github.com/backant-io/shepetal/pull/6
- https://github.com/backant-io/shepetal
- https://github.com/eySRbS4zgHuW3gMFZB2/soravo_electron/pull/41
- https://github.com/lionel509/boring.notch/issues/3
- https://github.com/Micaxes/whispr-bro/issues/1
- https://www.wensenwu.com/thoughts/wispr-flow-investigation
- https://levels.io/wispr-flow-granola-whoop-reverse-engineered
- https://getroutines.ai/transparency/wispr-flow
- https://www.getvoibe.com/resources/is-wispr-flow-safe/
- https://www.getvoibe.com/resources/wisprtype-vs-wispr-flow/
- https://www.getvoibe.com/resources/openai-whisper-vs-wispr-flow/
- https://embertype.com/blog/the-day-wispr-flow-banned-a-user/
- https://modelpiper.com/blog/wispr-flow-privacy-incident
- https://kintal.co/thinking/what-wispr-flow-actually-does
- https://www.speakoflow.com/blog/does-wispr-flow-work-offline
- https://www.forasoft.com/learn/ai-for-video-engineering/articles-ai/whisper-flow-app-engineering-walkthrough
- https://spokenly.app/blog/wispr-flow-review
- https://beebom.com/wispr-flow-ai-dictation-app-transcribes-voice-faster-than-typing
- https://chatgate.ai/post/wispr-flow

**Competitors and clones**
- https://aquavoice.com/blog/introducing-avalon
- https://aquavoice.com/llms.txt
- https://news.ycombinator.com/item?id=39828686
- https://willowvoice.com/blog/automatic-punctuation-dictation
- https://willowvoice.com/blog/wispr-flow-whisper-flow-willow-comparison
- https://superwhisper.com/docs/modes/built-in.md
- https://9to5google.com/2026/05/12/gemini-intelligence-announcement/
- https://android.gadgethacks.com/news/gboard-rambler-voice-typing-upgrade-explained-new-vs-existing-features/
- https://openwhispr.com/compare/wisprflow
- https://github.com/cjpais/Handy
- https://tryvoiceink.com/docs/contextual-awareness
- https://openalternative.co/alternatives/wisprflow

**Research and voice-agent infrastructure**
- https://arxiv.org/abs/2205.00620 (Teaching BERT to Wait)
- https://arxiv.org/pdf/2211.08726 (Streaming joint ASR + disfluency detection)
- https://arxiv.org/abs/2509.20321v1 (DRES)
- https://arxiv.org/pdf/2605.12242 (Mind the Pause)
- https://arxiv.org/pdf/1912.03393 (Re-translation strategies)
- https://arxiv.org/pdf/2004.03643 (Re-translation vs streaming)
- https://arxiv.org/html/2307.14743 (Whisper-Streaming / LocalAgreement)
- https://docs.livekit.io/reference/agents-js/classes/plugins_agents_plugin_deepgram.STTv2.html
- https://github.com/livekit/agents/issues/5536
