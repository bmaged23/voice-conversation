"""Interpretation cannot silently rewrite arbitrary content or override literal speech."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from voice_conversation import interpretation
from voice_conversation.settings import load_config

TEXT = "I mean effect as a verb meaning influence and effect as a noun meaning result."
EDIT = {"token_index": 2, "source": "effect", "replacement": "affect"}


def reply(edits, uncertain=False):
    return json.dumps({"edits": edits, "needs_clarification": uncertain})


def test_word_edit_preserves_punctuation_and_unedited_occurrences():
    raw = 'I mean "effect" as a verb meaning influence; effect means result. Budget: $42.50.'
    result = interpretation.apply_edits(raw, reply([EDIT]), 4)
    assert result.text == raw.replace('"effect"', '"affect"', 1)
    assert result.raw_text == raw
    assert result.changed and not result.needs_clarification


@pytest.mark.parametrize(
    "edit",
    [
        {"token_index": True, "source": "effect", "replacement": "affect"},
        {"token_index": 999, "source": "effect", "replacement": "affect"},
        {"token_index": 2, "source": "wrong-source", "replacement": "affect"},
        {"token_index": 2, "source": "effect", "replacement": "two words"},
        {"token_index": 2, "source": "effect", "replacement": "42"},
        {"token_index": 2, "source": "effect", "replacement": "<script>"},
    ],
)
def test_invalid_edit_rejected(edit):
    with pytest.raises(ValueError):
        interpretation.apply_edits(TEXT, reply([edit]), 4)


def test_duplicate_excess_and_uncertain_edits_rejected():
    for value, limit in [
        (reply([EDIT, EDIT]), 4),
        (reply([EDIT]), 0),
        (reply([EDIT], True), 4),
    ]:
        with pytest.raises(ValueError):
            interpretation.apply_edits(TEXT, value, limit)


def test_empty_edit_and_fenced_valid_json():
    result = interpretation.apply_edits(TEXT, "```json\n" + reply([]) + "\n```", 4)
    assert result.text == TEXT and result.status == "unchanged"


@pytest.mark.parametrize(
    "text",
    [
        "Repeat exactly: I mean effect as a verb meaning influence.",
        "Exactly repeat: I mean effect as a verb meaning influence.",
        "I mean seven people, not six.",
        "Explain the difference between effect and effect.",
    ],
)
@pytest.mark.asyncio
async def test_ordinary_or_literal_input_does_not_call_cloud(monkeypatch, text):
    complete = AsyncMock()
    monkeypatch.setattr(interpretation, "complete_text", complete)
    result = await interpretation.interpret_speech(
        text, None, {}, load_config()["interpretation"]
    )
    assert result.text == text and result.status == "skipped"
    complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_or_timed_out_resolution_asks_for_spelling(monkeypatch):
    for outcome in ["invalid json", TimeoutError("test deadline")]:
        complete = AsyncMock(
            side_effect=outcome if isinstance(outcome, Exception) else None,
            return_value=(outcome, {}),
        )
        monkeypatch.setattr(interpretation, "complete_text", complete)
        result = await interpretation.interpret_speech(
            TEXT, None, {}, load_config()["interpretation"]
        )
        assert (
            result.text == TEXT
            and result.needs_clarification
            and result.status == "unresolved"
        )


@pytest.mark.asyncio
async def test_cancellation_propagates(monkeypatch):
    monkeypatch.setattr(
        interpretation, "complete_text", AsyncMock(side_effect=asyncio.CancelledError)
    )
    with pytest.raises(asyncio.CancelledError):
        await interpretation.interpret_speech(
            TEXT, None, {}, load_config()["interpretation"]
        )


@pytest.mark.parametrize(
    "text",
    [
        "I mean principal as a moral rule and principal as the head of a school.",
        "To clarify, I mean stationary as writing paper and stationary as not moving.",
    ],
)
def test_definition_pairs_do_not_require_grammatical_jargon(text):
    assert interpretation.is_candidate(text, load_config()["interpretation"])


def test_preview_bounds_do_not_change_final_recognition(monkeypatch):
    from types import SimpleNamespace
    import numpy as np
    from voice_conversation import workers

    calls = []

    class Model:
        def transcribe(self, audio, **kwargs):
            calls.append(kwargs)
            return [SimpleNamespace(text=" example ")], None

    monkeypatch.setattr(workers, "_model", Model())
    monkeypatch.setattr(workers, "_settings", load_config()["stt"])
    audio = np.zeros(512, dtype=np.float32)
    workers.transcribe_preview(audio)
    workers.transcribe(audio)
    assert calls[0]["beam_size"] == 1 and calls[0]["max_new_tokens"] == 48
    assert calls[1]["beam_size"] == 3 and "max_new_tokens" not in calls[1]


@pytest.mark.parametrize(
    "edit",
    [
        {"token_index": 7, "source": "influence", "replacement": "create"},
        {"token_index": 5, "source": "verb", "replacement": "noun"},
    ],
)
def test_model_cannot_change_definitions_to_fit_recognized_spelling(edit):
    with pytest.raises(ValueError):
        interpretation.apply_edits(TEXT, reply([edit]), 4)
