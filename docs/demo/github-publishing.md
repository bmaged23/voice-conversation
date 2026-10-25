# GitHub demo hosting

Repository: https://github.com/bmaged23/voice-conversation

Player: https://bmaged23.github.io/voice-conversation/demo.html

Diagram: https://bmaged23.github.io/voice-conversation/architecture.html

GitHub Pages serves the `docs/` folder from the `main` branch. The MP4 and WebM
are ordinary tracked files and do not require Git LFS. Changes to documentation
and reviewed media are published by pushing to `main`.

Keep `.env`, `.venv`, `models`, caches, logs and raw recording frames excluded.
The static video player needs no API key, GPU, Python backend or speech models.
The live microphone conversation runs locally through `scripts/application/start_voice_app.py`.
