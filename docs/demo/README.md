# Voice demo

A ten-turn conversation plans a surprise space-themed birthday picnic, develops
a budget and vegan menu, handles a rain backup, and recalls the constraints.
The assistant uses a warm, upbeat speaking style.

The recording demonstrates the running Voca interface and the actual
STT → Ollama Cloud → TTS pipeline. The demo user is voiced by a local speech
synthesizer and supplied through a browser test microphone. It is an automated
conversation, not a recording of Bola's voice. Assistant responses are generated
live; no WebSocket responses or transcripts are mocked.

The final MP4 contains the user input and assistant playback audio, with the
actual browser screen recording. The digital soundtrack uses the audio buffers actually played in the browser and their start/stop timestamps, including the interruption cut. The reproduction helper is
`scripts/demo/record_conversation_demo.py`. It requires Playwright Chromium, FFmpeg and FFprobe,
local speech models, a running server, and a valid Ollama API key. It makes a
small number of paid/quota-consuming cloud requests.

The browser player uses an MP4 source and a VP9/Opus WebM fallback for browsers
without H.264/AAC support. Optional English captions are generated from the
actual recorded audio; they can contain transcription/timing errors. The
on-screen transcript can include the remainder of an interrupted generated
reply, which was not fully spoken; it is marked accordingly.

Recording preserves real elapsed conversation time. Browser playback timestamps place each audio buffer on the screen timeline, preserving silence and truncating interrupted playback at its actual stop time. There is no narration or background music.

This recording predates the GPU container release and used Nemotron. The current cloud default is Gemma 4 31B, selected after separate reasoning regressions; the original recorded dialogue remains unchanged.
