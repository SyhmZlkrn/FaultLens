"""Deterministic check that the report's sensor observations match the detector output.

The LLM verifier can miss a renamed sensor ("Nf rose 27.2 rpm" when the detector said NRc).
This check does not need a model: it reads the observation text (summary and each cause's
evidence lines), finds sensor codes, and compares the direction and any reading with a unit
against what the detector actually reported.

It is deliberately conservative: conditional or instructional text ("if T30 rises",
"check P30") and negations are skipped, so a flag means a clear contradiction.
"""
from __future__ import annotations

import re

from app.sensors import FEATURES, SENSOR_META

CODES = sorted((SENSOR_META[s][0] for s in FEATURES), key=len, reverse=True)
CODE_RE = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(map(re.escape, CODES)) + r")(?![A-Za-z0-9_])")
DIRECTION_WORDS = {
    "rising": r"ris(?:e|es|ing|en)|rose|increas\w*|upward|up|climb\w*|higher",
    "falling": r"fall(?:s|ing)?|fell|drop\w*|decreas\w*|downward|down|declin\w*|lower",
    "steady": r"steady|stable|flat|unchanged",
}
DIRECTION_RE = {d: re.compile(rf"\b(?:{p})\b", re.I) for d, p in DIRECTION_WORDS.items()}
READING_RE = re.compile(r"([-+]?\d+(?:\.\d+)?)\s*(rpm|degR|deg R|psia|lbm/s)\b")
SKIP_RE = re.compile(r"\b(if|when|unless|check|verify|confirm|monitor|watch|expect\w*|signature|"
                     r"would|should|could|might|may)\b", re.I)
NEGATION_RE = re.compile(r"\b(not|no|without|never)\b|n't\b", re.I)


# Sensor descriptions that contain another sensor's code ("phi" is the ratio of fuel flow to Ps30)
NAME_PHRASES = re.compile(r"(?:ratio of )?fuel[- ]flow (?:to|/) ?Ps30(?: ratio)?", re.I)
LEADING_DIRECTION_RE = re.compile(
    r"\b(?:" + "|".join(DIRECTION_WORDS.values()) + r")\s+$", re.I)


def _clauses(text: str) -> list[str]:
    # a full stop ends a clause only before a space or the end, so "45.0 rpm" stays whole
    return [c for c in re.split(r"\.(?=\s|$)|[;:\n]|\s-\s|\bwhile\b|\bwhereas\b|\bbut\b", text) if c.strip()]


def _direction(segment: str) -> str | None:
    hits = [(m.start(), d) for d, rx in DIRECTION_RE.items() for m in [rx.search(segment)] if m]
    return min(hits)[1] if hits else None


def _connector_only(text: str) -> bool:
    """True when text between two codes only joins them into a list ("Nc, NRc", "T24/T50", "Nc and NRc")."""
    return bool(re.fullmatch(r"[\s,/&]*(?:and|or)?[\s,/&]*", re.sub(r"\([^)]*\)?", "", text), re.I))


def _groups(clause: str) -> list[tuple[list[str], str, str | None]]:
    """Split a clause into (codes, text after them, claimed direction).

    Codes joined only by list words share the direction that follows them ("Nc and NRc rising")
    or the one written just before the first of them ("rising T24/T50"). Anything else stands alone.
    """
    matches = list(CODE_RE.finditer(clause))
    groups, pending, lead_open = [], [], False
    for i, m in enumerate(matches):
        code = m.group(1)
        prefix = clause[(matches[i - 1].end() if i else 0):m.start()]
        segment = clause[m.end():(matches[i + 1].start() if i + 1 < len(matches) else len(clause))]
        lead = LEADING_DIRECTION_RE.search(prefix)
        if lead and not pending:
            groups.append(([code], "", _direction(lead.group(0))))
            lead_open = True
            continue
        if lead_open and not pending and i and _connector_only(prefix):
            groups[-1][0].append(code)
            continue
        lead_open = False
        pending.append(code)
        direction = None if NEGATION_RE.search(segment) else _direction(segment)
        if direction or READING_RE.search(segment) or i + 1 == len(matches) or not _connector_only(segment):
            groups.append((pending, segment, direction))
            pending = []
    return groups


def _contradicts(claimed: str, s: dict) -> bool:
    """Reversed direction, or calling a moving sensor steady. A small change the detector calls
    steady may still be described as rising or falling, as long as the sign is right."""
    if claimed == s["direction"]:
        return False
    if s["direction"] == "steady" and claimed in ("rising", "falling"):
        return (claimed == "rising") != (s["change_over_window"] > 0)
    return True


def _close(a: float, b: float) -> bool:
    return abs(abs(a) - abs(b)) <= max(0.05 * abs(b), 0.06)


def check_sensor_claims(texts: list[str], assessment: dict) -> list[str]:
    """Return one plain message per observation that contradicts the detector output."""
    known = {s["code"]: s for s in assessment.get("all_sensors") or assessment.get("top_sensors") or []}
    problems = []
    for text in texts:
        for clause in _clauses(NAME_PHRASES.sub("fuel flow ratio", text or "")):
            if SKIP_RE.search(clause):
                continue
            for codes, segment, claimed in _groups(clause):
                readings = [float(n) for n, _unit in READING_RE.findall(segment)]
                quote = clause.strip()[:90]
                for code in codes:
                    s = known.get(code)
                    if s is None:
                        if claimed in ("rising", "falling") or readings:
                            problems.append(f'"{quote}": the detector did not report {code}.')
                        continue
                    if claimed and _contradicts(claimed, s):
                        problems.append(f'"{quote}": {code} is {s["direction"]} in the detector, not {claimed}.')
                group = [known[c] for c in codes if c in known]
                for value in readings:
                    if group and not any(_close(value, s["change_over_window"]) or _close(value, s["value_now"])
                                         for s in group):
                        problems.append(f'"{quote}": {value:g} does not match the detector for {", ".join(codes)}.')
    return list(dict.fromkeys(problems))


def report_observations(report) -> list[str]:
    """The parts of a report that state observations: the summary and each cause's evidence."""
    return [report.summary, *(e for c in report.likely_causes for e in c.evidence)]
