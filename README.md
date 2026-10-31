# assemblyai-tts-tinkering

Exploring AssemblyAI's full voice stack (streaming STT, Dictation API, LLM Gateway, AssemblyAI-TTS-1, Voice Agent API) to build a cascading STT -> LLM -> TTS agent with file-system tools inside its container.

## Research

- [AssemblyAI platform capabilities](research/assemblyai-platform-capabilities.md): what each product does, limits, pricing, SDK surface, LiveKit vs Pipecat, and a recommended architecture.
- [Wispr Flow system design](research/wispr-flow-system-design.md): how Wispr Flow's dictation cleanup, context use and low latency likely work, and what transfers to a real-time pipeline.
