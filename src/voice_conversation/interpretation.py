"""Conservative, auditable word repair for explicit speech clarifications.

The recognizer transcript stays unchanged. Only validated single-word edits can
enter conversation memory, and failed/uncertain interpretation asks for spelling.
No word-pair dictionary or unconditional spelling substitution is used.
"""

from dataclasses import dataclass, field
import json
import re
import time

from .cloud import complete_text

WORDS = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", re.UNICODE)
CLARIFICATION = re.compile(
    r"\b(?:i mean|i meant|to clarify|what i mean|by that i mean)\b", re.I
)
LINGUISTIC = re.compile(
    r"\b(?:noun|verb|adjective|adverb|word|spelled|spelling|meaning|definition)\b", re.I
)
REPEATED_DEFINITION = re.compile(r"\b([^\W\d_]+)\s+as\b.*\band\s+\1\s+as\b", re.I)
LITERAL_ACTION = re.compile(r"\b(?:say|repeat|quote|transcribe)\b", re.I)
LITERAL_MODE = re.compile(r"\b(?:exactly|verbatim|word for word)\b", re.I)


@dataclass(frozen=True)
class Interpretation:
    raw_text: str
    text: str
    edits: tuple = ()
    needs_clarification: bool = False
    status: str = "unchanged"
    seconds: float = 0
    usage: dict = field(default_factory=dict)

    @property
    def changed(self):
        return self.text != self.raw_text

    def packet(self):
        return {
            "raw_text": self.raw_text,
            "text": self.text,
            "edits": list(self.edits),
            "changed": self.changed,
            "needs_clarification": self.needs_clarification,
            "status": self.status,
        }


def is_candidate(text, settings):
    return bool(
        settings.get("enabled")
        and len(text) <= settings["max_input_characters"]
        and CLARIFICATION.search(text)
        and (LINGUISTIC.search(text) or REPEATED_DEFINITION.search(text))
        and not (LITERAL_ACTION.search(text) and LITERAL_MODE.search(text))
    )


def apply_edits(text, response, max_edits):
    """Validate the model proposal and splice words without rewriting other content."""
    content = response.strip()
    if content.startswith("```") and content.endswith("```"):
        content = "\n".join(content.splitlines()[1:-1])
    value = json.loads(content)
    if not isinstance(value, dict) or set(value) != {"edits", "needs_clarification"}:
        raise ValueError("Unexpected interpretation schema")
    edits = value["edits"]
    uncertain = value["needs_clarification"]
    if (
        type(uncertain) is not bool
        or not isinstance(edits, list)
        or len(edits) > max_edits
    ):
        raise ValueError("Invalid interpretation bounds")
    if uncertain and edits:
        raise ValueError("Uncertain interpretation cannot edit speech")
    matches = list(WORDS.finditer(text))
    seen = set()
    labels = {
        "noun",
        "verb",
        "adjective",
        "adverb",
        "meaning",
        "means",
        "spelled",
        "word",
        "term",
        "a",
        "an",
        "the",
    }
    words = [match.group().casefold() for match in matches]
    editable = {
        index
        for index, word in enumerate(words)
        if word not in labels
        and (
            (index > 0 and words[index - 1] in {"mean", "meant", "word", "term"})
            or (
                index + 1 < len(words)
                and words[index + 1] in {"as", "means", "meaning", "spelled"}
            )
        )
    }
    accepted = []
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {
            "token_index",
            "source",
            "replacement",
        }:
            raise ValueError("Unexpected word edit schema")
        index, source, replacement = (
            edit["token_index"],
            edit["source"],
            edit["replacement"],
        )
        if type(index) is not int or not 0 <= index < len(matches) or index in seen:
            raise ValueError("Invalid word index")
        if index not in editable:
            raise ValueError(
                "Edits must target the clarified word, not its definition or other facts"
            )
        if not isinstance(source, str) or source != matches[index].group():
            raise ValueError("Word edit source mismatch")
        if not isinstance(replacement, str) or not WORDS.fullmatch(replacement):
            raise ValueError("Replacement must be one word")
        seen.add(index)
        if source.casefold() != replacement.casefold():
            accepted.append(dict(edit))
    repaired = text
    for edit in sorted(accepted, key=lambda item: item["token_index"], reverse=True):
        match = matches[edit["token_index"]]
        repaired = (
            repaired[: match.start()] + edit["replacement"] + repaired[match.end() :]
        )
    return Interpretation(
        text,
        repaired,
        tuple(accepted),
        uncertain,
        "needs_spelling" if uncertain else "repaired" if accepted else "unchanged",
    )


async def interpret_speech(text, client, llm, settings):
    if not is_candidate(text, settings):
        return Interpretation(text, text, status="skipped")
    start = time.monotonic()
    tokens = [
        {"index": i, "word": match.group()}
        for i, match in enumerate(WORDS.finditer(text))
    ]
    request = json.dumps({"transcript": text, "tokens": tokens})
    try:
        output, usage = await complete_text(
            client,
            llm,
            [
                {"role": "system", "content": settings["system_prompt"]},
                {"role": "user", "content": request},
            ],
            think=settings["think"],
            max_tokens=settings["max_response_tokens"],
            timeout_seconds=settings["timeout_seconds"],
        )
        result = apply_edits(text, output, settings["max_word_edits"])
        return Interpretation(
            result.raw_text,
            result.text,
            result.edits,
            result.needs_clarification,
            result.status,
            time.monotonic() - start,
            usage,
        )
    except Exception:
        # No provider bodies, secrets or hidden reasoning enter errors or traces.
        return Interpretation(
            text,
            text,
            needs_clarification=True,
            status="unresolved",
            seconds=time.monotonic() - start,
        )
