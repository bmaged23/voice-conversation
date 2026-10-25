# Voca evaluation — 25 October 2026

These measurements belong to Voca, on a GTX 1660 Ti with 6 GiB VRAM.
Native development comparisons and initial container release evidence are separated below.
Cloud LLM hardware is outside local resource measurements.

| Component / comparison | Cases | Result |
| --- | ---: | --- |
| Whisper small.en CUDA baseline, beam 1 | 40 human recordings | WER **6.60%**, CER **2.80%** |
| Same decoder, noisy/quiet variants | 18 | WER **16.67%**, CER **7.27%** |
| Actual Silero + endpoint clip activation | 58 speech/stress + 6 non-speech clips | **58/58 detected**, **0/6 false activations** |
| Paired CPU / GPU decoder timing | 8 recordings | Median **2.668 / 0.455 s**, approximately **5.86×** decoder speedup |
| Kokoro CPU / GPU generation | 32 identical phrases | Median **2.093 / 0.418 s**, approximately **5.01×** generation speedup |
| Independent Whisper large-v3 audit of Kokoro output | 32 CPU + 32 GPU files | Both WER **8.52%**, CER **7.10%**; every paired recognition transcript identical |
| Original CPU-TTS browser journeys | 20 turns | **16/20** checks passed; failures retained |
| GPU interruption and recovery regression | 6 turns | **6/6** passed |
| Full GPU browser journeys | 20 turns | **17/20** checks passed, zero JavaScript errors |
| Clarification development dialogue revision | 21 turns | **18/21** passed; three homophone teaching failures retained |
| Offline unit/regression tests | 14 | **14/14** passed |

![Measured component inference](charts/component-latency.png)

![Baseline error rates](charts/speech-error-rates.png)

Aggregate machine-readable evidence is in [measurements](measurements/).
Frozen references and case definitions are under [`evaluation/datasets`](../../evaluation/datasets).
Raw waveform inputs, per-stage outputs and private traces remain local and ignored.

## References and scoring

Human speech is a preselected, gender-balanced 40-sentence subset of the official
[Google FLEURS English US test split](https://huggingface.co/datasets/google/fleurs),
CC-BY-4.0, revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd`.
The manifest records IDs, source text and audio hashes. Selection preceded inference.
Twenty sentences are development cases, twenty are validation cases. Noise variants
reuse development recordings and are not independent examples.

WER/CER aggregate edit counts over normalized references, rather than averaging
per-sentence percentages. Normalization lowercases NFKC text and replaces punctuation
with spaces; number spellings remain literal. CER includes spaces. Six raw decoder
non-speech probes produced four hallucinated words; they bypass VAD and do not prove
four live false turns. The real-browser silence checks passed.

An actual Silero/endpoint pass detected at least one speech turn in all 58
speech/stress clips and none in the six non-speech probes. This is clip-level
activation, with no human frame/boundary labels: it does not establish frame-level
accuracy, endpoint timing, or broad noise robustness. Its aggregate evidence is
[`vad-clip-activation.json`](measurements/vad-clip-activation.json).

TTS has fixed original text, saved waveform hashes, signal checks, generation timing
and independent known-English Whisper large-v3 recognition. This measures agreement,
not human MOS or perceptual quality. Numeric formatting contributes to errors, but
there are also lexical disagreements and a currency phrase requiring further review.
CPU/GPU runtime versions differ: these are deployment-configuration comparisons,
not an isolated hardware-only experiment. Neither speedup is a whole-conversation
speedup. Model loading is separate from warm generation/decode timings.

## Conversation checks and fixes

The connected journeys cover planning facts and corrections, story recall, teaching,
exact speech, interruption, arithmetic, injected cloud failure, recovery and silence.
They use frozen synthetic user recordings, real recognition, cloud streaming and
synthesis, with playback acknowledgements in Chromium. Keyword checks are necessary
regressions, not a comprehensive semantic judge.

The baseline exposed a factual follow-up failure, the acoustically ambiguous
“affect/effect” request and its subsequent examples, and an error banner that persisted
after successful recovery. Failed outputs are preserved. The prompt now emphasizes
question intent and factual consistency; the banner clears on the next turn.
First-content and idle-content deadlines bound empty cloud keepalives.

Beam 3 reduced development word errors from 42 to 39 out of 552 reference words and
restored question punctuation in one captured follow-up. It did not disambiguate
“affect/effect”. The default is now beam 3; the 40-case baseline table above remains
explicitly beam 1 and must not be presented as the new default's final score.

A GPU recovery run exposed a harness race: old-turn audio could satisfy the new
turn's completion predicate. The corrected predicate requires a final transcript
and current-turn reply. The earlier failed run is retained locally, not counted as
a model regression or silently overwritten. The corrected six-case suite passed.

The complete native GPU browser rerun passed 17/20 checks. The remaining failures were the story summary and the ambiguous teaching request plus its follow-up. Recovery and silence passed. A documentation rendering job briefly overlapped that functional run; its latency observations are not a dedicated isolated performance qualification. Subsequent container qualification is recorded separately below.

## Subsequent fixes and release policy

Removing a rigid response word count and explicitly preserving causes fixed the
targeted story-summary regression. Both Nemotron and Gemma were compared on the same
captured development transcripts; neither reliably recovered the intended spelling
after Whisper rendered both words as “effect”. That comparison did not establish a reason to switch models; a later numerical regression comparison did, as recorded below.

Version 2 of the dialogue adds a user clarification, retaining all 20 original
waveforms by hash and generating one additional input. Its native run passed 18/21:
the same three teaching turns remain limitations. The old version and results are
preserved. This revision tests clarification behavior; it is not a held-out benchmark.
The [release policy](../../evaluation/release_policy.json), frozen before image
qualification, requires all 18 other turns and at least 18/21 overall, alongside
explicit STT/TTS completion and error-rate thresholds. Known teaching failures stay
in the total and reports; this does not imply 21/21 accuracy.

Protocol regressions reproduce and prevent malformed playback acknowledgements
crashing a pending reply or crediting unplayed phrases. Browser transport checks
deliver an 80-frame burst in order without closing the session and reject prolonged
overflow at a bounded queue size. Fourteen offline tests cover these behaviors,
origin/session rejection, invalid controls and audio frames, interruption timing,
cloud content deadlines and phrase/playback ordering.

## Completed initial release and a blocked regression

[Release 40211491285](https://github.com/bmaged23/voice-conversation/actions/runs/40211491285)
passed hosted tests/build, GPU qualification, Docker Hub publication, anonymous pull
and normal startup for source `3ee337ef08c686ffd7b14a0c57eda5d5fce7d809`.
Its immutable public image is `bmaged23/voice-conversation@sha256:3961a412fe51c812bb07c2527cbae542babf23f3c05d3508c564dcc00cf7107b`.
The [aggregate evidence](measurements/initial-qualified-container.json) records
64/64 ASR executions, human WER/CER **6.60%/2.64%** with beam 3, 32/32 TTS generations
and independent audits, TTS agreement **8.52%/7.10%**, and **18/21** browser checks.
Its median warm phrase generation was **0.600 s**, separate from the native 0.418 s comparison.

[Candidate bf482a1](https://github.com/bmaged23/voice-conversation/actions/runs/40211839640)
passed speech checks but returned **58 dollars instead of 48** in the budget dialogue.
The gate [blocked publication](measurements/blocked-container-bf482a1.json).
It was not rerun unchanged to obtain a favorable score. Both old local candidates
were subsequently removed to reclaim laptop space; published registry artifacts remain.

## Reasoning configuration selection

Eight numerical/time regressions were frozen before one comparative run per configuration.
The captured failing budget context is retained in the public dataset, alongside
alternative budgets, expenses, multiplication, division, negatives, decimals and time.

| Configuration | Correct required answers | Median first text | Reported output tokens, all eight |
| --- | ---: | ---: | ---: |
| Nemotron 3 Nano, thinking off, temperature 0 | 7/8 | 0.570 s | 96 |
| Nemotron 3 Nano, thinking on, temperature 0 | 8/8 | 3.562 s | 4,108 |
| Gemma 4 31B, thinking off, temperature 0 | 8/8 | 0.420 s | 74 |

Answers were manually reviewed; [summary](measurements/reasoning-configuration-comparison.json)
and [synthetic outputs](measurements/reasoning-configuration-outputs.json) are retained.
Gemma with thinking off and temperature zero is the next configured candidate.
These are eight exposed development examples, not general reasoning rankings or
monetary-price comparisons. The new gate requires all eight reasoning regressions,
actual VAD clip checks and the existing speech/conversation criteria before publication.
Final lean-image qualification remains pending.
