# How Wispr Flow Works Under the Hood: A System-Design Teardown (revised)

**Date:** 2026-11-01 (revises the 2026-10-31 version)
**Scope:** Wispr Flow (wisprflow.ai), the closed-source voice dictation app from Wispr Inc. Everything below comes from public sources. Each claim carries one of four confidence labels.

- **[Confirmed]** means Wispr stated it, or a vendor case study Wispr took part in states it.
- **[Strongly implied]** means it follows directly from primary evidence, including direct reading of reverse-engineered client code.
- **[Third-party]** means a reviewer, competitor, journalist, or community analyst said it and I could not check it against a Wispr primary source.
- **[Speculation]** means it is my own inference.

> **Method note.** This revision was done from a desktop session where direct page fetches worked for most sites. I fetched and read these primary pages directly: Wispr's engineering and research posts (technical challenges, speech recognition challenges, supporting 100 languages, Canto, the Lab page), the What's New changelog, the privacy policy, terms of service, Data Controls page, and enterprise privacy overview; the docs.wisprflow.ai help articles on Context Awareness, Smart Formatting and Backtrack, Auto Cleanup, IDE use, Android formatting, the security FAQ, and Notetaker privacy; the Baseten case study; and the `wisprflow-sdk` README, `TECHNICAL_DETAILS.md`, and `_core.py` (via raw GitHub). I also read the SE Radio 703 transcript page, Computerworld, Dev Interrupted, VKTR, Pulse 2.0, and the community analyses listed in the sources. **Could not access:** x.com posts (HTTP 402), so the Wispr and Tanay Kothari posts on X are unverified; the docs.wisprflow.ai subprocessor article and `/privacy/overview` (both 404); the `backant-io/shepetal` PR #6 (404); Android Authority (403); and the Trust Center subprocessor list, which Wispr keeps behind an NDA. SE Radio 715 has no public transcript, only a publisher summary. My fetch tool returns condensed page text, so short quotes below are as close to verbatim as that allowed; check exact wording at the URL before quoting externally.

---

## Executive summary

1. **Did Wispr train its own STT model?** Yes, since 2026. Wispr previewed **Canto**, "the first speech model we've built ourselves", on 2026-08-17 alongside its Series B, published the technical post on 2026-09-17, and rolled it out to all users the same day **[Confirmed]**. Canto starts from an unnamed pretrained speech-text model, is trained with SFT and then GRPO reinforcement learning, and takes the user's dictionary terms as runtime context **[Confirmed]**. Press reports it at about 2B parameters **[Third-party press]**. Before Canto, Wispr described its recognizer as "an ensemble of speech recognition models" with per-language engine selection, without naming vendors **[Confirmed]**. The CTO said in January 2026 that "we host all of the models ourselves" **[Confirmed]**, and the client streamed to a Baseten-hosted model, so the main English path was most likely a self-hosted model on Baseten, with vendor APIs (OpenAI transcription, ElevenLabs) as fallbacks or for some languages **[Strongly implied / Third-party]**.
2. **Disfluent speech and self-corrections.** Cleanup is a separate LLM stage after ASR. Baseten's case study says it is a fine-tuned **Llama** model served with TensorRT-LLM and Baseten Chains **[Confirmed]**, and Wispr's terms say it "may use OpenAI or Anthropic LLMs" to generate outputs **[Confirmed]**. **Backtrack** removes fillers, false starts, and clear self-corrections using the whole dictation as context ("coffee at 2 actually 3" becomes "coffee at 3"), while keeping non-corrective uses of cue words **[Confirmed]**. Smart Formatting adds punctuation, lists, numbers as digits, paragraph breaks, and spoken commands like "new line" **[Confirmed]**. Auto Cleanup has None, Light (default), and Medium levels **[Confirmed]**.
3. **Context beyond model weights.** Confirmed by Wispr: app category, text before, after, and selected around the cursor, on-screen text read through accessibility APIs, names on screen, variable and function names visible in Cursor, Windsurf, and VS Code, the user's in-app identifier, the apps in the session, the personal dictionary, snippets, per-app Styles, and learning from user edits **[Confirmed]**. Wispr says it "does not take screenshots" **[Confirmed]**, yet the wire protocol has `screenshot`, `screen_ocr`, and (per a later analysis) chat-conversation fields **[Strongly implied / Third-party]**. Use of past dictations and "previous threads" for tone is reported in press interviews but not documented as a per-request input **[Third-party press]**.
4. **Low latency.** Target: formatted text within 700 ms of the end of speech, at **p99**, budgeted as <200 ms ASR, <200 ms LLM, and <200 ms network **[Confirmed]**. The LLM must process and generate 100+ tokens in under 250 ms **[Confirmed]**. The CTO credits a speculative decoding trick that guesses unchanged words will be copied through, cutting LLM latency "by over half in a lot of our cases" **[Confirmed]**. The client opens a bidirectional gRPC stream to Baseten, sends preferences and context first, streams audio during speech, and sends one FINAL commit on key release **[Strongly implied]**. Dictation latency fell 30% in the first half of 2026 **[Confirmed]**.
5. **Real-time and streaming cleanup.** Flow inserts cleaned text once, after release; it does not show a live cleaned transcript while dictating **[Strongly implied]**. The protocol carries partial `raw_text` and `formatted_text` frames, and one static analysis says the server uses "previous chunks' raw and LLM text for continuity" **[Strongly implied / Third-party]**, so some chunked server-side formatting probably exists. Wispr's Notetaker does show a live transcript and then re-processes the whole recording at the end **[Confirmed]**. Google's Gemini 3.5 Transcribe Live has a SMART mode that emits cleaned text per finalized segment, with speculative interim text in between **[Confirmed by Google docs]**. Aqua Voice's Realtime Mode shows live words but still lands text when you finish **[Confirmed by Aqua]**. Streaming cleanup is feasible with segment-level commit, a one-segment hold-back, and a final tail pass at release. Section 5 gives a concrete design on AssemblyAI's stack.

### Main corrections versus the 2026-10-31 version

- **Canto details.** The Canto page does not state a parameter count; "about 2B" comes from press. The distractor-vocabulary training was a research experiment that Wispr says "extend[s] beyond" the training used for the released model, so it is not a confirmed production technique. The comparison set (Google, OpenAI, AssemblyAI, Deepgram) is now confirmed directly; Canto lost to Gemini 3.1 Pro on Wispr's challenge set and all evaluations were English. The X-post figure of 3.4% WER could not be verified.
- **Pre-Canto ASR.** The old report called it "unknown". Wispr's own January 2026 post says it used an ensemble with per-language engine selection, and the CTO said Wispr hosts its models itself. That narrows the answer considerably.
- **Commit semantics.** The old report said every audio packet carries a `Commit(NON_FINAL)`. The SDK code sends NON_FINAL commits only after the Init and Context messages, sends audio packets with no commit, and attaches the single FINAL commit to the last packet.
- **Clipboard paste.** The old report sourced paste insertion to the BoringNotch issue, which does not say that. Wispr's own IDE doc confirms paste (Shift+Insert on Windows in IDEs).
- **Auto Cleanup levels.** The "High"/HEAVY level is no longer selectable; the documented levels are None, Light, Medium.
- **Aqua Voice.** Its "Streaming Mode" was renamed Realtime Mode in July 2026, lands text only when you finish, and runs on a third-party realtime speech provider rather than Aqua's Avalon model.
- **Hosting.** Wispr confirms AWS with Northern Virginia primary and Northern California failover; Baseten confirms dedicated deployments on AWS workload planes.
- **The 2025 screenshot incident.** On closer reading, the sources for the user ban and the CTO apology are competitor blogs citing other reviews; no primary record was found. It is downgraded to weakly sourced.
- **New primary evidence.** SE Radio 703 (speculative decoding, self-hosting, GPU co-location), Computerworld ("looks at your previous threads"), the "AI apps skip formatting" rule, and a new static analysis of client v1.6.1174 (HTTP and OpenAI fallbacks, mid-utterance context updates, server-side chunk continuity).

---

## 1. Did Wispr train its own STT model?

### Canto (2026)

- **Announcement and rollout.** VKTR and Pulse 2.0 reported Canto in preview on 2026-08-17, with the $280M Series B ([VKTR](https://www.vktr.com/ai-platforms/wispr-hits-2b-valuation-launches-canto-voice-model/); [Pulse 2.0](https://pulse2.com/wispr-raises-280-million-at-2-billion-valuation-as-revenue-grows-150-quarterly-and-voice-ai-push-accelerates/)) **[Third-party press]**. Wispr's changelog entry for 2026-09-17 says Flow now runs on Canto for all users ([What's new](https://wisprflow.ai/whats-new)) **[Confirmed]**. The Canto research post is dated the same day and is credited to the Wispr Advanced Interfaces Lab, led by Chief Science Officer Ariya Rastrow ([Canto](https://wisprflow.ai/canto); [Lab](https://wisprflow.ai/lab)) **[Confirmed]**.
- **Training** ([Canto](https://wisprflow.ai/canto)) **[Confirmed]**:
  - It starts from a model "pretrained on millions of hours of speech and text". The base model is not named.
  - Stage one is SFT on audio paired with reference transcripts.
  - Stage two is RL with GRPO. Several candidate transcripts are sampled per clip, each is scored (the example reward is 1 minus WER), and advantages are computed relative to the group.
  - User corrections become training signal. Forced-alignment confidence and the shape of each edit pick out likely recognition errors, and only those corrections are grafted into the reference.
- **Runtime context.** Canto receives vocabulary from the user's dictionary at inference time to recover names and rare terms **[Confirmed]**. Wispr also reports research runs with phonetically similar *distractor* terms. After RL, the model adopted the most similar distractors "nearly five times as often" as the SFT model, and mixing distractors with true terms in training reduced false-context following. Wispr notes these experiments go beyond the released model's training, so treat the distractor technique as research, not a confirmed production feature **[Confirmed as research]**.
- **Evaluation** ([Canto](https://wisprflow.ai/canto)) **[Confirmed as Wispr's claim; no independent benchmark]**:
  - On 10 hours of real dictations from 2,300+ speakers, Canto had the lowest WER among models from Google, OpenAI, AssemblyAI, and Deepgram.
  - On a 3-hour challenge set it ranked second, behind Gemini 3.1 Pro, which Wispr calls too large for real-time use. Gemini led on noisy audio.
  - It tied for lowest on LibriSpeech and was competitive but not leading on FLEURS and Common Voice.
  - All evaluations were English; exact WER values appear only in charts. A successor is being trained at more than 10x Canto's scale, with more languages and unified transcription plus diarization on the roadmap.
- **Press numbers.** About 2B parameters ([VKTR](https://www.vktr.com/ai-platforms/wispr-hits-2b-valuation-launches-canto-voice-model/)); WER in hard conditions falling from over 30% to roughly 5 to 10%, and an expected 30 to 35% fewer dictations needing edits ([Pulse 2.0](https://pulse2.com/wispr-raises-280-million-at-2-billion-valuation-as-revenue-grows-150-quarterly-and-voice-ai-push-accelerates/)) **[Third-party press quoting Wispr]**. A 3.4% WER figure attributed to an X post by CEO Tanay Kothari could not be checked because x.com was not reachable **[Unverified]**.

### What powered Flow before Canto

- **Wispr's own description.** CTO Sahaj Garg's January 2026 post says Flow "dynamically selects the most accurate ASR ... engine for each language" and "uses an ensemble of speech recognition models", which cut error rates by more than half in internal tests. It also uses "accent confidence scoring" to compare multiple transcriptions ([Supporting 100 languages](https://wisprflow.ai/research/supporting-languages)) **[Confirmed]**. The post names Scribe, Gemini, and Whisper only in a WER comparison, not as components of Flow.
- **Self-hosting.** On SE Radio 703 (2026-01-14), Garg said "we host all of the models ourselves" and described a speech model plus an LLM in the pipeline ([SE Radio 703](https://se-radio.net/2026/01/se-radio-703-sahaj-garg-on-low-latency-ai/)) **[Confirmed]**. The client's default gRPC target in April and June 2026 was a Baseten model (`model-v31pl413`) that returns both raw and formatted text ([wisprflow-sdk TECHNICAL_DETAILS](https://raw.githubusercontent.com/ThisisShashwat/wisprflow-sdk/main/TECHNICAL_DETAILS.md); [Wensen Wu](https://www.wensenwu.com/thoughts/wispr-flow-investigation)) **[Strongly implied]**. Together these mean the main path before Canto was a model Wispr deployed itself on Baseten. Which open or licensed model that was is not public **[Strongly implied / identity unknown]**.
- **Vendor fallbacks.** A transparency audit of the DPA's subprocessor annex says OpenAI Whisper is a fallback speech path and ElevenLabs is used for certain languages ([Routines](https://getroutines.ai/transparency/wispr-flow)) **[Third-party]**. A static analysis of client v1.6.1174 found a backend fallback that "proxies an OpenAI transcription" ([BoringNotch issue #3](https://github.com/lionel509/boring.notch/issues/3)) **[Third-party]**. Both fit the "ensemble" wording.
- **Changelog trail.** June 2026 entries mention an upgraded speech model in progress and say everyone was moved onto "the same current model" after some dictations had been handled by older models ([What's new](https://wisprflow.ai/whats-new)) **[Confirmed]**.
- **Motivation.** Wispr's research post argues that moving English WER from 3% to 2% "hardly made a dent" on its hard test sets, because the audio is ambiguous without context ([Speech recognition challenges](https://wisprflow.ai/research/speech-recognition-challenges)) **[Confirmed]**. A 2026 job listing asked for "scaling the personalization of our speech models and LLMs with fine-tuning and RL" ([Built In listing](https://builtin.com/job/ml-engineer/7257184)) **[Confirmed]**.

**Answer.** Wispr now runs its own model, Canto **[Confirmed]**. Before that it ran an ensemble that it describes but does not name, most likely a self-hosted model on Baseten for the main path with vendor APIs for fallback and some languages **[Strongly implied / Third-party]**.

---

## 2. Cleanup of disfluent and self-corrected speech

### Architecture

- **A separate LLM stage.** Baseten's case study says Wispr chose Llama "as the base for their real-time transcript cleanup step", fine-tuned it for users' context and preferences, and serves it with Baseten's TensorRT-LLM engine builder and Chains for multi-step inference ([Baseten](https://www.baseten.co/resources/customers/wispr-flow/)) **[Confirmed]**. Garg is quoted there saying Llama is "controllable and customizable". The version and size are not given.
- **Other LLMs.** Wispr's terms (updated 2026-08-19) say "Wispr may use OpenAI or Anthropic LLMs as Third-Party Services to generate Outputs" ([Terms](https://wisprflow.ai/terms)) **[Confirmed]**. Computerworld reports Llama 3.1 for text editing "combined with proprietary models from the likes of OpenAI" ([Computerworld](https://www.computerworld.com/article/4107331/wispr-ceo-interview-post-keyboard-office.html)) **[Third-party press]**. The DPA annex reportedly also lists Cerebras, Fireworks AI, OpenPipe, and Modal Labs ([Routines](https://getroutines.ai/transparency/wispr-flow)) **[Third-party]**. Which feature uses which model is not public. Command Mode, Polish and other Transforms, and Notetaker summaries are plausible users of the OpenAI and Anthropic models **[Speculation]**.
- **More than two models.** Garg said speculative decoding freed enough budget to add "a third and fourth model" to the pipeline ([SE Radio 703](https://se-radio.net/2026/01/se-radio-703-sahaj-garg-on-low-latency-ai/)) **[Confirmed]**. One client analysis reports a separate LLM call that extracts proper nouns from screen text ([Wensen Wu](https://www.wensenwu.com/thoughts/wispr-flow-investigation)) **[Third-party]**, and Wispr's context doc refers to "extracted names" per dictation ([Context Awareness](https://docs.wisprflow.ai/articles/4678293671-feature-context-awareness)) **[Confirmed]**. Another analysis lists client-requested pipeline steps "transcribe, align, format", plus optional sentence lowercasing, and a server-side "semantic auto-stop" model ([BoringNotch issue #3](https://github.com/lionel509/boring.notch/issues/3)) **[Third-party]**.
- **The wire protocol shows the split.** Server frames carry a `State` with `raw_text` and `formatted_text`, and a `Result` with HTML and plaintext and a status of FORMATTED, ERROR, or RAW_TRANSCRIPT. A `disable-formatting` header exists ([wisprflow-sdk](https://raw.githubusercontent.com/ThisisShashwat/wisprflow-sdk/main/TECHNICAL_DETAILS.md)) **[Strongly implied]**. Wispr's docs confirm that if formatting fails, Flow pastes the raw transcript ([Smart Formatting & Backtrack](https://docs.wisprflow.ai/articles/5373093536-how-do-i-use-smart-formatting-and-backtrack)) **[Confirmed]**.
- **Formatter conditioning variables** in the protocol ([wisprflow-sdk `_core.py`](https://raw.githubusercontent.com/ThisisShashwat/wisprflow-sdk/main/src/wisprflow_sdk/_core.py)) **[Strongly implied]**:
  - writing style (FORMAL, CASUAL, VERY_CASUAL, EXCITED), sent per app category (personal, work, email, other)
  - editing strength (VERBATIM, LIGHT, MEDIUM, HEAVY on the wire; how the UI levels map to it is the SDK author's guess)
  - app type (other, browser, personal, work, email, chatbot, developer)
  - personal dictionary, replacements, and snippets
- **AI apps skip formatting.** Dictations into apps Flow recognizes as AI apps, and Command Mode dictations, skip formatting by design ([Auto Cleanup](https://docs.wisprflow.ai/articles/4283510616-auto-cleanup-control-how-much-flow-edits-your-dictation-beta)) **[Confirmed]**. This matches the `chatbot` app type in the protocol.
- **Command Mode** is a separate voice feature for editing existing or selected text. Its edited text is pasted back ([Command Mode doc](https://docs.wisprflow.ai/articles/4816967992-how-to-use-command-mode)) **[Confirmed]**. The SDK implements it as `POST api.wisprflow.ai/llm/command_mode_route` with the full text, selection, instruction, and style settings ([wisprflow-sdk](https://raw.githubusercontent.com/ThisisShashwat/wisprflow-sdk/main/TECHNICAL_DETAILS.md)) **[Strongly implied]**. A static analysis says realtime "voice actions" use a WebSocket to a separate backend ([BoringNotch issue #3](https://github.com/lionel509/boring.notch/issues/3)) **[Third-party]**.

### Backtrack, fillers, and formatting

From Wispr's docs ([Smart Formatting & Backtrack](https://docs.wisprflow.ai/articles/5373093536-how-do-i-use-smart-formatting-and-backtrack); [Android formatting](https://docs.wisprflow.ai/articles/6568835559-why-wispr-flow-sometimes-removes-or-changes-words-on-android-smart-formatting); [Auto Cleanup](https://docs.wisprflow.ai/articles/4283510616-auto-cleanup-control-how-much-flow-edits-your-dictation-beta)) **[Confirmed]**:

- **Backtrack** removes filler words, false starts, and self-corrections. You can use a cue such as "actually", "scratch that", or "never mind", or just restate what you meant. Flow "uses your full dictation as context to decide what to change". Example: "Let's do coffee at 2 actually 3" becomes "Let's do coffee at 3". Only clear self-corrections are removed, so "I actually enjoyed the movie" survives.
- **Spelled corrections** replace an earlier word only when the spelled word sounds similar; a very different-sounding correction is ignored.
- **Smart Formatting** adds punctuation, lists (from "one... two..." or "first... second..."), line and paragraph breaks, and fixes filler, grammar, and capitalization. It "does not correct misheard words". Spoken numbers become digits with units ("four four five cleaners" becomes "445 cleaners"). It inserts paragraph breaks at topic shifts, drops spoken list markers, and avoids em dashes unless dictated.
- **Spoken commands.** "period", "comma", "question mark", "colon", "new line", "new paragraph", and similar. Line and paragraph commands work even with Smart Formatting off.
- **Auto Cleanup levels.** None (raw transcript including fillers and false starts), Light (default; removes fillers and fixes grammar), and Medium (may reword for clarity). High is no longer selectable. Writing Styles also control trailing periods (Formal keeps them; Casual drops them for up to 10 sentences).
- **Undo.** The original transcript is kept. "Undo AI edit" in Recent Activity restores it.
- **Length-dependent behavior.** Garg said short messages keep filler words to preserve tone, while longer dictations get more cleanup ([SE Radio 703](https://se-radio.net/2026/01/se-radio-703-sahaj-garg-on-low-latency-ai/)) **[Confirmed]**.

This is semantic rewriting by an LLM conditioned on the whole utterance, not rule-based deletion **[Strongly implied]**. The examples need right-hand context: "2 actually 3" cannot be resolved until "3" is heard.

### Learning from edits

- "Flow's formatter learns from real user edits (punctuation, spacing, and grammar corrections)", including regional email conventions and greeting styles ([Supporting 100 languages](https://wisprflow.ai/research/supporting-languages)) **[Confirmed]**.
- The engineering post describes capturing edits on device, deciding which generalize, and training a "local RL policy" toward a product that "never makes the same mistake twice" ([Technical challenges](https://wisprflow.ai/post/technical-challenges)) **[Confirmed]**. It also notes that "LLMs are phenomenal at recall, but very low precision" for style rules.
- About 25 to 30% of users opt in to sharing data for training ([Computerworld](https://www.computerworld.com/article/4107331/wispr-ceo-interview-post-keyboard-office.html)) **[Third-party press]**.
- **Not disclosed:** prompt format, model sizes, whether styles are separate adapters, and routing between Llama and the OpenAI or Anthropic models. "100+ tokens in under 250 ms" is consistent with an 8B-class model on modern GPUs with TensorRT-LLM plus speculative decoding **[Speculation]**.

---

## 3. Context beyond the model weights

### Confirmed by Wispr

From the Context Awareness article ([docs](https://docs.wisprflow.ai/articles/4678293671-feature-context-awareness)) **[Confirmed]**:

- It is on by default. On Mac it needs Accessibility permission; Windows needs none.
- Inputs: app info with a category (Email, Work messaging, Personal messaging, Other); textbox contents before, selected, and after the cursor; on-screen text; variable and file names in coding apps; your user identifier within the app; and the apps in your current session.
- Uses: names on screen (email recipients, for example) for proper nouns and capitalization; casing and punctuation that match surrounding text; email greetings and sign-offs; continuing a sentence after an emoji or closing quote.
- Exclusions: password fields, sensitive and numeric-only fields, URL bars, placeholder text, and banking apps. Custom or web password fields "may be read like normal text fields".
- "Flow works from text and does not take screenshots."
- Captured text and extracted names are cleared when the dictation ends.
- **With context off** on Mac and Windows, Flow still sends the app name and website domain, and "nearby text is used only on the device and is not sent". That implies some formatting logic (spacing or casing continuation) runs locally **[Strongly implied]**.
- On iPhone, the keyboard sends the text around the cursor, the selection, and the app name.

Other confirmed context sources:

- **IDEs.** Flow reads "visible variable, function, and class names from the frontmost supported IDE" (Cursor, Windsurf, VS Code), which requires the IDE's screen-reader mode. File tagging inserts `@file` mentions in Cursor and Windsurf chat for files open in a tab or visible in the sidebar ([IDE doc](https://docs.wisprflow.ai/articles/6434410694-use-flow-with-cursor-vs-code-and-other-ides)) **[Confirmed]**.
- **Dictionary.** A personal dictionary with starred words, usage-based ranking, auto-add, and org-wide shared entries ([What's new](https://wisprflow.ai/whats-new)) **[Confirmed]**, fed to Canto as runtime vocabulary ([Canto](https://wisprflow.ai/canto)) **[Confirmed]**.
- **Styles.** Per-category tone settings (Personal, Work, Email, Other), with app recognition for Instagram, Discord, Signal, and LinkedIn ([What's new](https://wisprflow.ai/whats-new); [Styles doc](https://docs.wisprflow.ai/articles/2368263928-how-to-setup-flow-styles)) **[Confirmed]**.
- **Personal history in principle.** Wispr's research post frames recognition as using app context, "history of relevant topics they talk about", common names and terms, and voice embeddings ([Speech recognition challenges](https://wisprflow.ai/research/speech-recognition-challenges)). The engineering post describes "context-conditioned ASR models (conditioned on speaker qualities, surrounding context, and individual history)" ([Technical challenges](https://wisprflow.ai/post/technical-challenges)) **[Confirmed as direction; not documented as shipped inputs]**.

### Reported in interviews, not documented

- Kothari told Computerworld that Flow "looks at your previous threads" to infer tone, such as formality or starting in lowercase ([Computerworld](https://www.computerworld.com/article/4107331/wispr-ceo-interview-post-keyboard-office.html)) **[Third-party press]**. This most likely means the visible conversation in the active app rather than a server-side history store **[Speculation]**.
- The Deep View says Flow uses screen context, conversation history, and corrections ([The Deep View](https://archive.thedeepview.com/p/wispr-flow-preps-voice-ai-s-next-breakthrough)) **[Third-party press]**.

### What the client sends (reverse-engineered)

The `ContextRequest` in the gRPC stream has these fields ([wisprflow-sdk](https://raw.githubusercontent.com/ThisisShashwat/wisprflow-sdk/main/TECHNICAL_DETAILS.md)) **[Strongly implied]**:

- **Textbox:** `before_text`, `after_text`, `selected_text`, `textbox_contents`
- **Screen:** `content_text`, `content_html`, `screenshot` (bytes)
- **App:** `app_name`, `bundle_id`, `url`, `session_apps`
- **Dynamic vocabulary** (up to 50 items each, gated by `allow_dynamic_vocab`): `screen_ax`, `screen_ocr`, `variable_names`, `file_names`

`InitRequest` carries the profile, languages, vocabulary, replacements, snippets, and styles.

A later static analysis of v1.6.1174 adds an optional chat-conversation field in the context message, optional prior state in Init, and an `updateContext` call that re-sends context mid-utterance ([BoringNotch issue #3](https://github.com/lionel509/boring.notch/issues/3)) **[Third-party; written by an AI agent doing a static read]**.

Wensen Wu's analysis of v1.4.752 logs found accessibility walks of 194 to 214 elements at depth 9, proper nouns extracted by a separate LLM call, an hourly `/history/upload` of metadata, and a local `flow.sqlite` holding audio, ASR and formatted text, edited text, textbox contents, and accessibility text ([Wensen Wu](https://www.wensenwu.com/thoughts/wispr-flow-investigation)) **[Third-party]**. The local database means past dictations exist on device, but nothing shows them being sent with each request **[Unknown]**.

### Screenshots: unresolved

The protocol has `screenshot` and `screen_ocr` fields, and the local database has a `screenshot` column **[Strongly implied / Third-party]**. Wispr's doc says it does not take screenshots **[Confirmed]**. A transparency audit quotes Wispr's security FAQ describing a separate "Screen OCR" component that is "default off" ([Routines](https://getroutines.ai/transparency/wispr-flow)) **[Third-party]**. Reports of a 2025 incident in which active-window screenshots were uploaded and a user was banned rest on competitor blogs citing other reviews, with no primary record ([Embertype](https://embertype.com/blog/the-day-wispr-flow-banned-a-user/); [ModelPiper](https://modelpiper.com/blog/wispr-flow-privacy-incident)) **[Third-party, weakly sourced]**. The likely reconciliation is an optional, off-by-default OCR path, but that is not confirmed **[Speculation]**.

### Data handling

- Hosting is AWS in the US, primary Northern Virginia with Northern California failover; transcription is cloud-only, with no on-prem or offline option ([Enterprise privacy](https://wisprflow.ai/post/enterprise-privacy-and-security-overview)) **[Confirmed]**.
- Third-party LLM providers do not train on the data, which is "generally deleted within 30 days" ([Privacy policy](https://wisprflow.ai/privacy-policy)). The Data Controls page says Wispr "always maintains zero data retention agreements with all third-party AI providers", with a Notetaker exception ([Data Controls](https://wisprflow.ai/data-controls)) **[Confirmed; the two statements are not fully consistent]**.
- Training on user data is controlled by "Improve the model for everyone" (formerly Privacy Mode) and is off for Enterprise and HIPAA accounts ([Data Controls](https://wisprflow.ai/data-controls)) **[Confirmed]**.
- The subprocessor list is behind an NDA in the Trust Center ([Enterprise privacy](https://wisprflow.ai/post/enterprise-privacy-and-security-overview)). The audit reports 34 entities in DPA Annex 2, including AWS, OpenAI, Anthropic, Google, Baseten, OpenPipe, Fireworks AI, Cerebras, ElevenLabs, and Modal Labs ([Routines](https://getroutines.ai/transparency/wispr-flow)) **[Third-party]**. Groq appears in no source.

---

## 4. How Flow achieves low latency

### Published numbers

| Metric | Value | Source | Label |
|---|---|---|---|
| End of speech to formatted text | within 700 ms | [Wispr](https://wisprflow.ai/post/technical-challenges) (2025-09-11) | Confirmed |
| Budget split | ASR <200 ms, LLM <200 ms, network <200 ms "from anywhere around the world" | [Wispr](https://wisprflow.ai/post/technical-challenges) | Confirmed |
| Percentile | p99; "we don't care at all about p50" | [Baseten](https://www.baseten.co/resources/customers/wispr-flow/) | Confirmed |
| LLM step | 100+ tokens processed and generated in <250 ms | [Baseten](https://www.baseten.co/resources/customers/wispr-flow/); Garg on [SE Radio 703](https://se-radio.net/2026/01/se-radio-703-sahaj-garg-on-low-latency-ai/) ("50 words or a hundred words ... 250 milliseconds") | Confirmed |
| Hiring target | "<500ms LLM inference for millions of requests from everywhere around the world" | [Built In listing](https://builtin.com/job/ml-engineer/7257184) | Confirmed |
| Trend | "Dictation latency is down 30% since the start of the year" (2026-07-09) | [What's new](https://wisprflow.ai/whats-new) | Confirmed |
| Scale | about 1B words dictated per month (Sept 2025); 99.99% uptime target | [Wispr](https://wisprflow.ai/post/technical-challenges) | Confirmed |

### Techniques Wispr has named

- **Speculative decoding on copy-heavy output.** Garg described guessing that unchanged words will repeat and verifying the guess, which cut LLM latency "by over half in a lot of our cases" ([SE Radio 703](https://se-radio.net/2026/01/se-radio-703-sahaj-garg-on-low-latency-ai/)) **[Confirmed]**. Cleanup output is nearly the same as the input, so drafting from the input transcript (prompt-lookup style) accepts long runs of tokens **[Strongly implied]**.
- **Budget reallocation.** The team measures each hop and moves budget between steps; saving network time can pay for a larger LLM. Smaller or quantized models lost accuracy ([SE Radio 703](https://se-radio.net/2026/01/se-radio-703-sahaj-garg-on-low-latency-ai/)) **[Confirmed]**. Wispr keeps deploying larger models within the same budget because user edits cost more time than inference ([Technical challenges](https://wisprflow.ai/post/technical-challenges)) **[Confirmed]**.
- **Co-location.** An incident with one GPU in California and another in the Midwest added 300 to 400 ms; the fix put both in one region ([SE Radio 703](https://se-radio.net/2026/01/se-radio-703-sahaj-garg-on-low-latency-ai/)) **[Confirmed]**.
- **Serving stack.** TensorRT-LLM engines, Chains for the multi-step pipeline, dedicated autoscaling deployments on AWS workload planes in regions near users ([Baseten](https://www.baseten.co/resources/customers/wispr-flow/)) **[Confirmed]**.
- **Tail latency.** p99 problems usually come from the network, so Wispr times every hop ([SE Radio 703](https://se-radio.net/2026/01/se-radio-703-sahaj-garg-on-low-latency-ai/)) **[Confirmed]**.

### What overlaps with speech and what runs after release

From the SDK ([TECHNICAL_DETAILS](https://raw.githubusercontent.com/ThisisShashwat/wisprflow-sdk/main/TECHNICAL_DETAILS.md); [`_core.py`](https://raw.githubusercontent.com/ThisisShashwat/wisprflow-sdk/main/src/wisprflow_sdk/_core.py)) **[Strongly implied]**:

1. `GET api.wisprflow.ai/warmup` before the stream.
2. One bidirectional gRPC call to `model-<id>.grpc.api.baseten.co`, method `flow_api.v1.TranscriptionService/TranscribeStream`, with both a Wispr bearer token and a Baseten API key in headers.
3. `InitRequest` (profile, languages, vocabulary, styles), then `Commit(NON_FINAL)`.
4. `ContextRequest` (app, textbox, screen, dynamic vocabulary), then `Commit(NON_FINAL)`.
5. Audio packets (16 kHz mono PCM16 in the SDK) with no commit attached, streamed as they are captured.
6. The last packet carries `Commit(FINAL)`, which corresponds to key release.
7. The server streams back `State` frames (raw and formatted text), `Result` frames, and heartbeats. One retry after 500 ms on UNAVAILABLE, DEADLINE_EXCEEDED, or RESOURCE_EXHAUSTED.

The real client may encode Opus instead of WAV/PCM; logs show an Opus encoder, behind a feature flag ([Wensen Wu](https://www.wensenwu.com/thoughts/wispr-flow-investigation); [BoringNotch issue #3](https://github.com/lionel509/boring.notch/issues/3)) **[Third-party]**. The v1.6.1174 analysis also reports a 4 s heartbeat watchdog (2 s after commit), a parallel HTTP fallback that races gRPC for clips under 30 s, a backend fallback to OpenAI transcription, a Modal candidate host, a one-hour probation for failed hosts, and no on-device model or VAD ([BoringNotch issue #3](https://github.com/lionel509/boring.notch/issues/3)) **[Third-party]**. Wensen Wu saw an HTTP fallback at `chain-o232k03l.api.baseten.co`, which is a Baseten Chains URL **[Third-party]**.

What follows **[Strongly implied unless marked]**:

- Connection setup, auth, preferences, and context all land before the user finishes speaking, so none of it is on the post-release critical path.
- Audio upload overlaps speech, and the server can run ASR incrementally, so at release only the audio tail is left to decode. That is how <200 ms ASR after end of speech works for long dictations.
- The LLM pass on the full utterance runs after FINAL, because Backtrack needs right-hand context. The 250 ms budget for 100+ tokens describes rewriting a paragraph at once **[Strongly implied]**. The "previous chunks" detail in the v1.6.1174 analysis suggests that long dictations are formatted in chunks, with each chunk conditioned on earlier raw and LLM output **[Third-party / Speculation on mechanism]**.
- Insertion is one paste after release. Wispr's IDE doc confirms paste (Shift+Insert on Windows in IDEs), and Command Mode output is "pasted back" **[Confirmed]**.
- Nothing runs offline. There is no local ASR or LLM ([Enterprise privacy](https://wisprflow.ai/post/enterprise-privacy-and-security-overview)) **[Confirmed]**.

---

## 5. Can cleanup run in real time, while streaming?

### What Wispr does

- **Dictation.** Text is inserted once, after release **[Strongly implied]**. I found no Wispr doc, changelog entry, or review describing cleaned text shown live during dictation; the docs describe pasting after you finish and offering "Undo AI edit" afterwards **[Strongly implied from absence]**. The protocol can return partial `formatted_text` frames, and the SDK queues them, but the SDK's own callback only fires after `finish()` and nothing shows Flow displaying partials ([`_core.py`](https://raw.githubusercontent.com/ThisisShashwat/wisprflow-sdk/main/src/wisprflow_sdk/_core.py)) **[Strongly implied]**.
- **Server-side chunking.** The "previous chunks' raw and LLM text for continuity" finding means the server likely formats long dictations piecewise, which would be incremental cleanup hidden from the user ([BoringNotch issue #3](https://github.com/lionel509/boring.notch/issues/3)) **[Third-party]**.
- **Notetaker.** It shows a live transcript during meetings and "re-processes the full recording" at the end ([What's new](https://wisprflow.ai/whats-new), 2026-08-05) **[Confirmed]**. That is a two-pass design: provisional live text, then an authoritative full pass.
- **Why Flow avoids it.** Retracting text already pasted into another app's text field is fragile. Holding everything until release sidesteps the problem, at the cost of needing a very fast full-utterance LLM pass **[Speculation]**.

### What competitors do

- **Aqua Voice** ([aquavoice.com/llms.txt](https://aquavoice.com/llms.txt)) **[Confirmed by Aqua]**:
  - Instant Mode (default) shows text "~450ms after you stop speaking", runs on Aqua's own Avalon models, and formats to match the app.
  - Realtime Mode (formerly Streaming Mode, renamed July 2026) shows words live in the Aqua toolbar, but text lands in the target app when you finish. It "streams audio to a third-party realtime speech provider".
  - Deep Context takes one screenshot at the start of each dictation (opt-in) and extracts words likely to be misheard.
  - In the 2024 Launch HN, the founders said Aqua is "6 models working together", that "the real-time text is non-final tokens", and that a restarted sentence keeps only its last version ([Launch HN](https://news.ycombinator.com/item?id=39828686)) **[Confirmed by founders, 2024]**. Aqua shows live text only in its own surface, which is what makes revision safe.
- **Google Gemini 3.5 Transcribe and Gboard Rambler.** The Live API emits `interim_input_transcription`, a "speculative partial hypothesis", and `input_transcription` when a segment finalizes at a pause or turn end. In SMART mode the final field contains "the cleaned, formatted response", with disfluencies removed and spoken corrections resolved ([Gemini Live transcription docs](https://ai.google.dev/gemini-api/docs/live-api/live-transcribe?hl=en); [Google blog](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-5-transcribe/), 2026-08-26) **[Confirmed]**. The docs do not say whether interim text is cleaned. This is segment-level streaming cleanup: commit at each pause, revise nothing already final. Rambler on Gboard uses the model ([Google blog](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-5-transcribe/)) **[Confirmed]**. Whether Rambler cleans live or after transcription is described inconsistently in coverage ([Gadget Hacks](https://android.gadgethacks.com/news/gboard-rambler-voice-typing-upgrade-explained-new-vs-existing-features/); [TechCrunch](https://techcrunch.com/2026/05/12/google-adds-gemini-powered-dictation-to-gboard-which-could-be-bad-news-for-dictation-startups/)) **[Third-party]**.
- **AssemblyAI Dictation API** ([docs](https://www.assemblyai.com/docs/dictation.md); [architecture guide](https://www.assemblyai.com/use-cases/dictation-app-architecture)) **[Confirmed]**:
  - `POST dictation.assemblyai.com/v1/transcribe/live` reads the multipart body as it arrives, so audio uploads during speech; the config part must come first.
  - Transcription (Universal-3.5 Pro) and an LLM rewrite run in one call. The response has the verbatim `text` and the rewritten `llm_response`.
  - The rewrite is one-shot after audio ends, with a best-effort deadline; on timeout it returns `llm_error: "timeout"` with the transcript intact.
  - Inputs: `stt_prompt` (up to 6,000 characters), `keyterms_prompt` (up to 100 terms), `llm_instruction` (replaces the default cleanup), and `rewrite_mode` fast or smart.
  - AssemblyAI's own guide frames the choice as "does text appear during the utterance, or after key release?" and recommends streaming for the former.
- **Blurt**, AssemblyAI's open-source macOS app, makes one HTTP request per utterance to the live endpoint, pre-warms the connection on key press, sends recent session dictations (capped near 4,096 characters), text before the cursor, key terms, and style instructions, and pastes via a synthesized Cmd+V. Its README says audio is read back from disk at release rather than streamed ([GitHub](https://github.com/assemblyai/blurt)) **[Confirmed]**. So Blurt is Flow's design minus streaming upload and minus screen context.
- **Superwhisper** runs ASR (local Parakeet, cloud Nova 3, and others) and then an optional LLM "mode". Plain Voice to Text skips the LLM and is fastest; Super mode reads the app, selected text, and clipboard. No streaming cleanup is documented ([Superwhisper docs](https://superwhisper.com/docs/modes/built-in.md)) **[Confirmed]**.
- **Open-source clones** (OpenWhispr, Handy, VoiceInk, and similar) follow push-to-talk, batch ASR on release, an optional LLM rewrite, and paste. None implements streaming cleanup ([OpenWhispr](https://openwhispr.com/compare/wisprflow); [Handy](https://github.com/cjpais/Handy); [VoiceInk](https://tryvoiceink.com/docs/contextual-awareness)) **[Third-party; not re-checked in this pass]**.

### Research and engineering techniques

- **The core difficulty.** A self-correction is a non-local edit. "Send it Tuesday, no, Wednesday" rewrites a word about a second back, and "scratch that" can delete a sentence. An incremental cleaner must either wait, revise, or speculate.
- **Commit and revise, measured as erasure.** Re-translation re-runs a model on each growing prefix. Normalized erasure (NE) counts tokens deleted from the previous output per final token. In Arivazhagan et al. (ICASSP 2020), biased beam search (favoring the previous output) plus masking the last k tokens cut NE from 2.11 to 0.12 with BLEU going from 20.40 to 20.17 ([arXiv 1912.03393](https://arxiv.org/pdf/1912.03393)). A follow-up defines "low-revision" as NE below 0.2, under one revised token per five output tokens, and finds re-translation in that regime matches or beats dedicated streaming systems ([arXiv 2004.03643](https://arxiv.org/pdf/2004.03643)). Both map directly onto a cleanup LLM: bias toward the previously emitted cleaned text, and keep the last k words provisional.
- **LocalAgreement.** Whisper-Streaming commits only the prefix on which consecutive hypotheses agree, with about 3.3 s latency on long-form English ([arXiv 2307.14743](https://arxiv.org/abs/2307.14743)). The same policy works on cleaned output: commit the cleaned prefix that two successive cleanup runs agree on.
- **Disfluency detection with learned lookahead.** "Teaching BERT to Wait" (NAACL 2022) trains a streaming tagger that decides per token whether to label now or wait for more words, giving comparable accuracy to non-streaming models with lower flicker and lower latency than fixed-lookahead baselines ([arXiv 2205.00620](https://arxiv.org/abs/2205.00620)). A joint streaming ASR plus disfluency model beats a BERT cascade on accuracy and latency ([arXiv 2211.08726](https://arxiv.org/abs/2211.08726)).
- **LLM disfluency removal.** The DRES benchmark found that segmenting input helps even long-context models, that reasoning models over-delete fluent words, and that fine-tuning raises precision at the cost of generalization ([arXiv 2509.20321v1](https://arxiv.org/abs/2509.20321v1)). "Mind the Pause" (ACL 2026) uses a tagger to flag disfluent tokens and guide an LLM rewriter; it is offline, but the tagger-guides-rewriter split suits streaming ([arXiv 2605.12242](https://arxiv.org/abs/2605.12242)).
- **Speculative cleanup.** Run cleanup on partial transcripts in the background and reuse the result if the final transcript matches. Wispr's copy-through speculative decoding is the per-token version of the same idea ([SE Radio 703](https://se-radio.net/2026/01/se-radio-703-sahaj-garg-on-low-latency-ai/)).

### Recommendation: a streaming cleanup stage on AssemblyAI's stack

The building blocks exist today **[Confirmed]**:

- **Universal-3.6 Pro Realtime** streaming emits an early partial at about 750 ms, continuous partials about every second, and exactly one formatted end-of-turn transcript per turn. Turns end on terminal punctuation after `min_turn_silence` (default 100 ms) or at `max_turn_silence` (default 1,000 ms). `prompt` and `keyterms_prompt` can be combined and updated mid-stream with `UpdateConfiguration` ([migration guide](https://assemblyai.com/docs/streaming/migration-guides/universal-to-universal-3-5-pro-streaming); [model selection](https://www.assemblyai.com/docs/streaming/universal-3-pro)).
- **LLM Gateway** hosts `qwen3.5-4b-32k-fast` on AssemblyAI's GPUs with `stream: true`; AssemblyAI reports 612 ms average on full voice rewrites versus 1,138 ms for GPT-4.1 ([AssemblyAI blog](https://www.assemblyai.com/blog/qwen-4b-llm-gateway), 2026-08-26).
- **Dictation API** does a one-shot transcribe plus rewrite for a final authoritative pass ([docs](https://www.assemblyai.com/docs/dictation.md)).

A design built on these, with my estimates marked **[Speculation]**:

1. **Push context early.** At session start, send dictionary terms and on-screen entities as `keyterms_prompt` and a short description as `prompt`, as Flow sends Init and Context before audio. Update them with `UpdateConfiguration` when the focused app changes.
2. **Use the formatted turn as the unit of commit.** Treat each end-of-turn transcript (or each sentence inside a long turn) as a segment. Keep exactly one segment provisional. When segment i+1 arrives, clean it with the committed cleaned text plus raw segment i as context, and let the model return either "append" or a structured edit (replace or delete within the provisional segment). Commit segment i once segment i+1 does not open with a correction cue.
3. **Gate long-range corrections with a cheap detector.** A regex or small tagger for cues ("actually", "no wait", "scratch that", "I mean", "never mind") decides whether the new segment may touch earlier text. Most segments are plain appends, so most cleanup calls are short and cheap. A rare "scratch all that" triggers a full re-clean of the turn.
4. **Speculate on partials.** Every partial (about once a second) can fire a background cleanup of the provisional segment. Cache results by raw text; if the final turn matches the speculated partial, reuse the cleanup and skip a model call.
5. **Bias toward the previous output.** Pass the prior cleaned version of the provisional segment and instruct the model to change only what the new words require, the LLM analogue of biased beam search. Track normalized erasure on the displayed text and aim for NE below 0.2.
6. **Show provisional text only in your own surface.** Put live cleaned text in an overlay or your own editor, as Aqua and Notetaker do. Insert into third-party apps only committed segments, or everything at release.
7. **Release path.** On key release, send `ForceEndpoint` so the last turn finalizes immediately, then clean only the provisional tail. Added post-release work becomes one short segment instead of a paragraph, plausibly 100 to 300 ms on the 4B gateway model versus about 600 ms for a full rewrite **[Speculation, scaled from AssemblyAI's 612 ms figure]**. Optionally run the Dictation API rewrite on the whole utterance afterwards for stored transcripts.
8. **For the voice agent in this repo,** nobody reads the cleaned text, so flicker costs nothing. The simplest path is to skip a visible cleanup stage, give the agent LLM the formatted turns with an instruction to honor the latest self-correction, and gate tool calls and TTS playback on the confirmed end-of-turn transcript. Add the segment cleaner only where a person sees or stores the text **[Speculation]**.

| Stage (end of speech to text) | Flow-style one-shot | Segment-commit streaming |
|---|---|---|
| Endpoint or release handling | key release, then FINAL | `ForceEndpoint` on release |
| ASR finalize | tail only (audio already streamed) | tail only |
| Cleanup | whole utterance (Flow budget 200 to 250 ms) | last segment only |
| Visible live text | none | provisional segment in own UI |
| Risk | long dictations grow cleanup time | long-range corrections need a re-clean |

---

## 6. Reverse engineering and community analyses

- **wisprflow-sdk** (ThisisShashwat). Unofficial Python SDK that patches `app.asar` to dump the runtime config written after `getDesiredGrpcModelInfo()`, then speaks the gRPC protocol with hand-encoded protobuf. It reuses the desktop app's Supabase session from `session.json`. It caps sessions at 300 s and 25 MB ([TECHNICAL_DETAILS](https://raw.githubusercontent.com/ThisisShashwat/wisprflow-sdk/main/TECHNICAL_DETAILS.md)) **[Strongly implied]**. The dynamic model lookup suggests the client picks a deployment ID at runtime, for example per language or experiment arm **[Speculation]**.
- **BoringNotch issue #3** (2026-10-20). A static read of v1.6.1174 by an AI agent ("Sonnet scout"), with H/M/L confidence labels. Findings: Electron app plus a Swift helper that owns OS signals; gRPC with unary `Transcribe` and duplex `TranscribeStream`; Baseten host with a Modal candidate path; HTTP and OpenAI-proxy fallbacks; `updateContext`; candidate beams with alignment scores, SNR, and volume in server state; server-side semantic auto-stop ([issue](https://github.com/lionel509/boring.notch/issues/3)) **[Third-party]**.
- **Wensen Wu** (April 2026, v1.4.752). Process listing, `strings`, log reading, and SQLite queries, with no traffic interception. Findings: CGEventTap key handling, accessibility walks, Opus encoder logs, endpoints on Baseten, `api.wisprflow.ai`, `api-east.wisprflow.ai`, Supabase, PostHog, Sentry, Segment, and Datadog; unsandboxed app ([write-up](https://www.wensenwu.com/thoughts/wispr-flow-investigation)) **[Third-party]**.
- **soravo_electron PR #41** (2026-10-30). Confirms Electron and `app.asar` on Windows v1.6.1337 ([PR](https://github.com/eySRbS4zgHuW3gMFZB2/soravo_electron/pull/41)) **[Third-party]**.
- **Gaps.** I found no published mitmproxy capture that names the LLM behind the Baseten endpoint, no Hacker News teardown thread, and no Wispr conference talk with architecture slides. The model behind the endpoint is invisible to the client.

---

## What is confirmed vs inferred

| Claim | Status | Key source |
|---|---|---|
| <700 ms target after end of speech; 200/200/200 ms budget | Confirmed | [Wispr](https://wisprflow.ai/post/technical-challenges) |
| p99 target; 100+ tokens in <250 ms; fine-tuned Llama; TensorRT-LLM; Chains | Confirmed | [Baseten](https://www.baseten.co/resources/customers/wispr-flow/) |
| Speculative decoding cut LLM latency by over half; models self-hosted | Confirmed | [SE Radio 703](https://se-radio.net/2026/01/se-radio-703-sahaj-garg-on-low-latency-ai/) |
| OpenAI or Anthropic LLMs may generate outputs | Confirmed | [Terms](https://wisprflow.ai/terms) |
| Canto in-house; SFT plus GRPO; runtime dictionary context; default since 2026-09-17 | Confirmed | [Canto](https://wisprflow.ai/canto), [What's new](https://wisprflow.ai/whats-new) |
| Canto about 2B parameters | Third-party press | [VKTR](https://www.vktr.com/ai-platforms/wispr-hits-2b-valuation-launches-canto-voice-model/) |
| Pre-Canto: ensemble with per-language engine selection | Confirmed | [Wispr](https://wisprflow.ai/research/supporting-languages) |
| Pre-Canto main path self-hosted on Baseten; OpenAI and ElevenLabs fallbacks | Strongly implied / Third-party | SDK, [Routines](https://getroutines.ai/transparency/wispr-flow) |
| Backtrack, Smart Formatting, Auto Cleanup None/Light/Medium | Confirmed | [Docs](https://docs.wisprflow.ai/articles/5373093536-how-do-i-use-smart-formatting-and-backtrack) |
| Context: app category, cursor text, on-screen text, IDE identifiers, session apps | Confirmed | [Docs](https://docs.wisprflow.ai/articles/4678293671-feature-context-awareness) |
| Protocol has screenshot, OCR, AX, URL, bundle ID, style and strength enums | Strongly implied | [wisprflow-sdk](https://raw.githubusercontent.com/ThisisShashwat/wisprflow-sdk/main/TECHNICAL_DETAILS.md) |
| Chat-conversation context, `updateContext`, chunk continuity on server | Third-party (AI-agent static read) | [BoringNotch #3](https://github.com/lionel509/boring.notch/issues/3) |
| Previous threads used for tone | Third-party press | [Computerworld](https://www.computerworld.com/article/4107331/wispr-ceo-interview-post-keyboard-office.html) |
| gRPC to Baseten; Init and Context before audio; single FINAL commit | Strongly implied | [`_core.py`](https://raw.githubusercontent.com/ThisisShashwat/wisprflow-sdk/main/src/wisprflow_sdk/_core.py) |
| Paste-based insertion | Confirmed | [IDE doc](https://docs.wisprflow.ai/articles/6434410694-use-flow-with-cursor-vs-code-and-other-ides) |
| Live cleaned text during dictation | No evidence | |
| Notetaker live transcript plus full re-process | Confirmed | [What's new](https://wisprflow.ai/whats-new) |
| 2025 screenshot upload incident and CTO apology | Third-party, weakly sourced | [Embertype](https://embertype.com/blog/the-day-wispr-flow-banned-a-user/) |
| Groq used | No evidence | |

---

## Sources

**Wispr primary (fetched directly)**
- https://wisprflow.ai/post/technical-challenges (Sahaj Garg, 2025-09-11)
- https://wisprflow.ai/research/speech-recognition-challenges (Sahaj Garg, 2025-09-17)
- https://wisprflow.ai/research/supporting-languages (Sahaj Garg, 2026-01-19)
- https://wisprflow.ai/canto (2026-09-17)
- https://wisprflow.ai/lab
- https://wisprflow.ai/whats-new
- https://wisprflow.ai/privacy-policy (updated 2026-08-19)
- https://wisprflow.ai/terms (updated 2026-08-19)
- https://wisprflow.ai/data-controls (updated 2026-08-18)
- https://wisprflow.ai/post/enterprise-privacy-and-security-overview
- https://docs.wisprflow.ai/articles/4678293671-feature-context-awareness
- https://docs.wisprflow.ai/articles/5373093536-how-do-i-use-smart-formatting-and-backtrack
- https://docs.wisprflow.ai/articles/4283510616-auto-cleanup-control-how-much-flow-edits-your-dictation-beta
- https://docs.wisprflow.ai/articles/6568835559-why-wispr-flow-sometimes-removes-or-changes-words-on-android-smart-formatting
- https://docs.wisprflow.ai/articles/6434410694-use-flow-with-cursor-vs-code-and-other-ides
- https://docs.wisprflow.ai/articles/4816967992-how-to-use-command-mode (via search summary)
- https://docs.wisprflow.ai/articles/2368263928-how-to-setup-flow-styles (via search summary)
- https://docs.wisprflow.ai/articles/3467817258-security-and-compliance-faq
- https://docs.wisprflow.ai/articles/4497184932-notetaker-privacy-and-security-overview
- https://builtin.com/job/ml-engineer/7257184 (Wispr ML Engineer listing, removed 2026-01-05)

**Not accessible in this pass**
- https://x.com/tankots/status/2100680985423843608 and https://x.com/WisprFlow/status/2110085776369471596 (HTTP 402)
- https://docs.wisprflow.ai/articles/5375461355-subprocessors-third-party-security (404)
- https://trust.wispr.ai/ (subprocessor list under NDA)
- https://github.com/backant-io/shepetal/pull/6 (404)

**Vendor, press, and interviews**
- https://www.baseten.co/resources/customers/wispr-flow/
- https://se-radio.net/2026/01/se-radio-703-sahaj-garg-on-low-latency-ai/ (2026-01-14)
- https://se-radio.net/2026/04/se-radio-715-sahaj-garg-on-designing-for-ambiguity-in-human-input/ (summary only)
- https://linearb.io/dev-interrupted/podcast/wispr-keyboard-bottleneck-vibe-coding-sahaj-garg (2026-02-24)
- https://www.computerworld.com/article/4107331/wispr-ceo-interview-post-keyboard-office.html (2025-12-31)
- https://archive.thedeepview.com/p/wispr-flow-preps-voice-ai-s-next-breakthrough (2026-03-21)
- https://www.vktr.com/ai-platforms/wispr-hits-2b-valuation-launches-canto-voice-model/ (2026-08-17)
- https://pulse2.com/wispr-raises-280-million-at-2-billion-valuation-as-revenue-grows-150-quarterly-and-voice-ai-push-accelerates/ (2026-08-17)
- https://www.aixventures.com/fireside-chat-with-tanay-kothari-at-wispr-flow (VC summary, undated)

**Reverse engineering and privacy analyses**
- https://github.com/ThisisShashwat/wisprflow-sdk
- https://raw.githubusercontent.com/ThisisShashwat/wisprflow-sdk/main/TECHNICAL_DETAILS.md
- https://raw.githubusercontent.com/ThisisShashwat/wisprflow-sdk/main/src/wisprflow_sdk/_core.py
- https://github.com/lionel509/boring.notch/issues/3
- https://github.com/eySRbS4zgHuW3gMFZB2/soravo_electron/pull/41
- https://www.wensenwu.com/thoughts/wispr-flow-investigation
- https://getroutines.ai/transparency/wispr-flow
- https://embertype.com/blog/the-day-wispr-flow-banned-a-user/
- https://modelpiper.com/blog/wispr-flow-privacy-incident

**Competitors and clones**
- https://aquavoice.com/llms.txt
- https://news.ycombinator.com/item?id=39828686
- https://ai.google.dev/gemini-api/docs/live-api/live-transcribe?hl=en
- https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-5-transcribe/
- https://android.gadgethacks.com/news/gboard-rambler-voice-typing-upgrade-explained-new-vs-existing-features/
- https://techcrunch.com/2026/05/12/google-adds-gemini-powered-dictation-to-gboard-which-could-be-bad-news-for-dictation-startups/
- https://superwhisper.com/docs/modes/built-in.md
- https://openwhispr.com/compare/wisprflow
- https://github.com/cjpais/Handy
- https://tryvoiceink.com/docs/contextual-awareness

**AssemblyAI**
- https://www.assemblyai.com/docs/dictation.md
- https://www.assemblyai.com/use-cases/dictation-app-architecture
- https://github.com/assemblyai/blurt
- https://www.assemblyai.com/blog/qwen-4b-llm-gateway
- https://www.assemblyai.com/docs/streaming/universal-3-pro
- https://assemblyai.com/docs/streaming/migration-guides/universal-to-universal-3-5-pro-streaming

**Research**
- https://arxiv.org/pdf/1912.03393 (Re-translation strategies, ICASSP 2020)
- https://arxiv.org/pdf/2004.03643 (Re-translation versus streaming, IWSLT 2020)
- https://arxiv.org/abs/2307.14743 (Whisper-Streaming, LocalAgreement)
- https://arxiv.org/abs/2205.00620 (Teaching BERT to Wait, NAACL 2022)
- https://arxiv.org/abs/2211.08726 (Streaming joint ASR and disfluency detection, ICASSP 2023)
- https://arxiv.org/abs/2509.20321v1 (DRES)
- https://arxiv.org/abs/2605.12242 (Mind the Pause, ACL 2026)
