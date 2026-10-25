"""Literal word/character error metrics; number spellings are intentionally retained."""

import re, unicodedata


def normalize(text):
    return " ".join(
        re.sub(r"[^\w\s]", " ", unicodedata.normalize("NFKC", text).lower()).split()
    )


def edits(reference, hypothesis):
    # DP entries carry cost and substitution/deletion/insertion counts.
    previous = [(i, 0, 0, i) for i in range(len(hypothesis) + 1)]
    for i, a in enumerate(reference, 1):
        current = [(i, 0, i, 0)]
        for j, b in enumerate(hypothesis, 1):
            c, s, d, n = previous[j - 1]
            options = [(c + (a != b), s + (a != b), d, n)]
            c, s, d, n = previous[j]
            options.append((c + 1, s, d + 1, n))
            c, s, d, n = current[j - 1]
            options.append((c + 1, s, d, n + 1))
            current.append(min(options, key=lambda x: x[0]))
        previous = current
    return previous[-1]


def score(reference, hypothesis):
    r, h = normalize(reference), normalize(hypothesis)
    words = r.split()
    cost, s, d, i = edits(words, h.split())
    charcost, *_ = edits(r, h)
    return {
        "reference_words": len(words),
        "reference_characters": len(r),
        "word_errors": cost,
        "character_errors": charcost,
        "wer": cost / max(1, len(words)),
        "cer": charcost / max(1, len(r)),
        "substitutions": s,
        "deletions": d,
        "insertions": i,
        "normalized_exact": r == h,
        "empty_hypothesis": not bool(h),
        "hallucinated_words_on_empty_reference": len(h.split()) if not r else 0,
    }


def aggregate(rows):
    scores = [r["metrics"] for r in rows if "metrics" in r]
    result = {
        k: sum(s[k] for s in scores)
        for k in (
            "reference_words",
            "reference_characters",
            "word_errors",
            "character_errors",
            "substitutions",
            "deletions",
            "insertions",
            "hallucinated_words_on_empty_reference",
        )
    }
    result.update(
        samples=len(scores),
        wer=result["word_errors"] / max(1, result["reference_words"]),
        cer=result["character_errors"] / max(1, result["reference_characters"]),
        exact_rate=sum(s["normalized_exact"] for s in scores) / max(1, len(scores)),
    )
    return result
