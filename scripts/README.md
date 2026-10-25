# Project tools

Run commands from the repository root, using the project environment.

| Folder | Purpose | Main entrypoint |
| --- | --- | --- |
| application | Launch the app with CUDA libraries | `python -m scripts.application.start_voice_app` |
| setup | Download pinned speech assets | `python -m scripts.setup.download_speech_models` |
| dependencies | Export installed version snapshots | `python -m scripts.dependencies.export_installed_versions` |
| validation | Configuration, cloud, speech and browser checks | `python -m scripts.validation.validate_configuration` |
| demo | Record/render/caption the existing conversation demo | `python -m scripts.demo.record_conversation_demo` |
| documentation | Render the animated pipeline | `python -m scripts.documentation.render_pipeline_animation` |

Model evaluation and Docker release tools will have separate `evaluation/` and `release/` folders. The [filename migration map](../docs/reference/filename-migration.json) records moved commands; duplicate wrappers are not retained. Existing public demo/media URLs are preserved. Model/cloud checks need the configured assets/key and can consume account allowance.
