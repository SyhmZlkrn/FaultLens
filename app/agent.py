"""The diagnosis agent.

Pipeline: detector output -> retrieve evidence -> diagnose (LLM on AMD Token Factory) ->
enforce rules in code -> verify (second LLM pass) -> draft work order for human approval.

The LLM proposes. Code enforces the safety rules. A person approves.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Literal, Optional

from pydantic import BaseModel, Field

from app import config
from app.checks import check_sensor_claims, report_observations
from app.sensors import FEATURES, SENSOR_META, asset_name

PROMPTS = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (PROMPTS / "system.md").read_text(encoding="utf-8")
VERIFIER_PROMPT = (PROMPTS / "verifier.md").read_text(encoding="utf-8")


# ---------- output schema ----------
class Cause(BaseModel):
    cause: str
    evidence: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    likelihood: Literal["high", "medium", "low"] = "medium"


class Action(BaseModel):
    step: str
    priority: Literal["immediate", "next_shift", "planned"] = "next_shift"
    citations: list[str] = Field(default_factory=list)


class WorkOrder(BaseModel):
    title: str
    asset: str
    priority: Literal["P1", "P2", "P3"] = "P2"
    description: str
    estimated_downtime_hours: Optional[float] = None
    parts_or_tools: list[str] = Field(default_factory=list)


class Report(BaseModel):
    summary: str
    severity: Literal["normal", "warning", "critical"]
    likely_causes: list[Cause] = Field(default_factory=list)
    recommended_actions: list[Action] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainties: list[str] = Field(default_factory=list)
    escalate: bool = False
    escalation_reason: Optional[str] = None
    work_order: Optional[WorkOrder] = None
    # filled in by code, not the model
    verification: dict = Field(default_factory=dict)
    guardrail_notes: list[str] = Field(default_factory=list)


# ---------- evidence ----------
def build_queries(assessment: dict) -> list[str]:
    qs = [f"{s['code']} {s['label']} {s['direction']}" for s in assessment["top_sensors"]]
    codes = " ".join(f"{s['code']} {s['direction']}" for s in assessment["top_sensors"])
    qs.append(f"gas turbine degradation signature {codes}")
    return qs


def gather_evidence(retriever, assessment: dict, k_manual: int = 4, k_incidents: int = 3) -> list[dict]:
    seen, evidence = set(), []
    for q in build_queries(assessment):
        for src, k in (("manual", 2), ("incident", 1)):
            for hit in retriever.search(q, k=k, source=src):
                if hit["id"] not in seen:
                    seen.add(hit["id"])
                    evidence.append(hit)
    manual = [e for e in evidence if e["source"] == "manual"][:k_manual]
    incidents = [e for e in evidence if e["source"] == "incident"][:k_incidents]
    # always include escalation rules and work order standards
    for must in ("MAN-09", "MAN-10"):
        if must not in {m["id"] for m in manual}:
            for c in retriever.chunks:
                if c["id"] == must:
                    manual.append({**c, "score": None})
    return manual + incidents


# ---------- tidy model output before validation ----------
_LIKELIHOOD = {"likely": "medium", "possible": "low", "very high": "high", "very low": "low"}
_ACTION_PRIORITY = {"next shift": "next_shift", "next-shift": "next_shift", "nextshift": "next_shift",
                    "urgent": "immediate", "now": "immediate", "scheduled": "planned"}


EVIDENCE_ID = re.compile(r"\b(?:MAN-\d{2}|INC-\d{4}-\d{3})\b")


def _citations(item: dict, *text_keys: str) -> list[str]:
    """The item's citations; if the model left them empty, take ids it wrote in the text instead.

    apply_guardrails still drops any id that was not in the evidence.
    """
    cited = item.get("citations") or []
    if isinstance(cited, str):
        cited = EVIDENCE_ID.findall(cited)
    cited = [str(x).strip() for x in cited if str(x).strip()]
    if not cited:
        text = " ".join(str(v) for k in text_keys for v in (item.get(k) if isinstance(item.get(k), list) else [item.get(k)]))
        cited = list(dict.fromkeys(EVIDENCE_ID.findall(text)))
    return cited


def _clean(value, default: str, allowed: set[str], aliases: dict[str, str]) -> str:
    v = str(value or "").strip().lower()
    v = aliases.get(v, v)
    return v if v in allowed else default


# DeepSeek-V4-Flash on Token Factory sometimes glues "aine"/"ainer" onto a word ("steadyaine",
# "Ps30ainer"), even at temperature 0. Repair it only on sensor codes and direction words.
_GLITCH = re.compile(r"\b(" + "|".join(sorted({SENSOR_META[s][0] for s in FEATURES}, key=len, reverse=True))
                     + r"|steady|stable|rising|falling)(?:ainer|aine)\b")


def _repair(value):
    if isinstance(value, str):
        return _GLITCH.sub(r"\1", value)
    if isinstance(value, list):
        return [_repair(v) for v in value]
    if isinstance(value, dict):
        return {k: _repair(v) for k, v in value.items()}
    return value


def normalize_raw(raw: dict) -> dict:
    """Fix the small format slips open-weight models make ("High", "next shift", 80 for 0.8).

    Only formatting is changed here. The safety rules still run afterwards in apply_guardrails.
    """
    raw = _repair(dict(raw))
    raw["severity"] = _clean(raw.get("severity"), "warning", {"normal", "warning", "critical"}, {})
    try:
        conf = float(raw.get("confidence", 0.5))
    except (TypeError, ValueError):
        conf = 0.5
    if conf > 1.0:
        conf = conf / 100 if conf <= 100 else 1.0
    raw["confidence"] = min(max(conf, 0.0), 1.0)
    for key in ("likely_causes", "recommended_actions", "uncertainties"):
        if not isinstance(raw.get(key), list):
            raw[key] = []
    causes = []
    for c in raw["likely_causes"]:
        if isinstance(c, dict) and c.get("cause"):
            c = {**c, "likelihood": _clean(c.get("likelihood"), "medium", {"high", "medium", "low"}, _LIKELIHOOD)}
            c["citations"] = _citations(c, "cause", "evidence")
            c["evidence"] = [str(x) for x in c.get("evidence") or []]
            causes.append(c)
    raw["likely_causes"] = causes
    actions = []
    for a in raw["recommended_actions"]:
        if isinstance(a, dict) and a.get("step"):
            a = {**a, "priority": _clean(a.get("priority"), "next_shift",
                                         {"immediate", "next_shift", "planned"}, _ACTION_PRIORITY)}
            a["citations"] = _citations(a, "step")
            actions.append(a)
    raw["recommended_actions"] = actions
    raw["uncertainties"] = [str(u) for u in raw["uncertainties"]]
    raw["escalate"] = bool(raw.get("escalate", False))
    wo = raw.get("work_order")
    if isinstance(wo, dict):
        wo = dict(wo)
        wo["title"] = str(wo.get("title") or "Inspect unit")
        wo["asset"] = str(wo.get("asset") or "")
        wo["description"] = str(wo.get("description") or "")
        wo["priority"] = _clean(wo.get("priority"), "p2", {"p1", "p2", "p3"}, {}).upper()
        try:
            hrs = wo.get("estimated_downtime_hours")
            wo["estimated_downtime_hours"] = None if hrs in (None, "") else float(hrs)
        except (TypeError, ValueError):
            wo["estimated_downtime_hours"] = None
        if not isinstance(wo.get("parts_or_tools"), list):
            wo["parts_or_tools"] = []
        raw["work_order"] = wo
    else:
        raw["work_order"] = None
    raw["summary"] = str(raw.get("summary") or "No summary returned.")
    return raw


def summarize_verification(check: dict) -> dict:
    """Turn the verifier's per-claim checks into the summary the UI shows.

    The verdict is computed here, from the failed checks, rather than trusted from the model:
    models often list claims they found fine, which would otherwise count as problems.
    """
    if "checks" not in check:
        return check
    failed = [c for c in check.get("checks") or [] if isinstance(c, dict) and c.get("ok") is False]
    def pick(kind: str) -> list[str]:
        return [f"{c.get('claim', '')} ({c.get('reason', '')})" for c in failed if c.get("issue") == kind]
    other = [f"{c.get('claim', '')} ({c.get('reason', '')})" for c in failed
             if c.get("issue") not in ("unsupported", "invented", "safety")]
    return {"supported": not failed, "checked": len(check.get("checks") or []),
            "unsupported_claims": pick("unsupported") + other, "invented_values": pick("invented"),
            "safety_issues": pick("safety"), "note": check.get("note", "")}


# ---------- guardrails (deterministic) ----------
def apply_guardrails(report: Report, assessment: dict, evidence_ids: set[str]) -> Report:
    notes = []
    # 1. citations must point at evidence we actually gave the model
    for item in [*report.likely_causes, *report.recommended_actions]:
        bad = [c for c in item.citations if c not in evidence_ids]
        if bad:
            notes.append(f"Removed citations not in evidence: {', '.join(bad)}")
            item.citations = [c for c in item.citations if c in evidence_ids]
    uncited = [c.cause for c in report.likely_causes if not c.citations]
    if uncited:
        notes.append("Some causes have no supporting citation; confidence lowered.")
        report.confidence = min(report.confidence, 0.5)

    # 1b. observations must match what the detector measured (catches renamed or reversed sensors)
    mismatches = check_sensor_claims(report_observations(report), assessment)
    if mismatches:
        notes += [f"Sensor claim does not match the detector: {m}" for m in mismatches[:3]]
        report.confidence = min(report.confidence, 0.5)

    # 2. severity can only go UP from what the detector says, never down
    order = ["normal", "warning", "critical"]
    if order.index(report.severity) < order.index(assessment["severity"]):
        notes.append(f"Severity raised to detector level ({assessment['severity']}).")
        report.severity = assessment["severity"]

    # 3. escalation rules
    reasons = []
    if report.severity == "critical":
        reasons.append("detector severity is critical")
    if report.confidence < config.CONFIDENCE_ESCALATE_BELOW:
        reasons.append(f"confidence {report.confidence:.2f} below {config.CONFIDENCE_ESCALATE_BELOW}")
    if reasons and not report.escalate:
        report.escalate = True
        report.escalation_reason = "; ".join(reasons)
        notes.append("Escalation forced by rule.")

    # 4. work order sanity
    if report.work_order:
        report.work_order.asset = asset_name(assessment["unit"])
        if report.severity == "critical" and report.work_order.priority != "P1":
            report.work_order.priority = "P1"
            notes.append("Work order priority set to P1 for critical severity.")
    report.guardrail_notes = list(dict.fromkeys([*report.guardrail_notes, *notes]))
    return report


# ---------- main entry ----------
LLMFn = Callable[[str, str], tuple[dict, dict]]


def diagnose(assessment: dict, retriever, llm_fn: LLMFn | None = None, verify: bool = True,
             on_step: Callable[[str], None] | None = None) -> tuple[Report, list[dict], dict]:
    """Returns (report, evidence, llm_meta). on_step, if given, receives a short progress line per stage."""
    step = on_step or (lambda _msg: None)
    if llm_fn is None:
        from functools import partial

        from app.llm import chat_json
        llm_fn = partial(chat_json, on_step=step)

    if assessment["severity"] == "normal":
        return Report(summary="Unit operating within its learned healthy pattern. No action needed.",
                      severity="normal", confidence=0.9), [], {}

    evidence = gather_evidence(retriever, assessment)
    step(f"Found {len(evidence)} evidence records: {', '.join(e['id'] for e in evidence)}")
    payload = {
        "asset": {"id": asset_name(assessment["unit"]), "type": "Gas turbine (simulated)",
                  "current_cycle": assessment["cycle"]},
        "detector": assessment,
        "evidence": [{"id": e["id"], "source": e["source"], "title": e["title"], "text": e["text"]}
                     for e in evidence],
    }
    step("Writing the diagnosis on AMD Token Factory (usually 30 to 70 s)...")
    raw, meta = llm_fn(SYSTEM_PROMPT, json.dumps(payload, separators=(",", ":")))
    step(f"Diagnosis written by {meta.get('model', 'the model')} in {meta.get('latency_s', 0):.0f} s.")
    report = Report.model_validate(normalize_raw(raw))
    report = apply_guardrails(report, assessment, {e["id"] for e in evidence})

    if verify:
        step("Checking every claim against its cited evidence (second AMD Token Factory call)...")
        try:
            check, vmeta = llm_fn(VERIFIER_PROMPT, json.dumps(
                {"report": report.model_dump(exclude={"verification", "guardrail_notes"}),
                 "detector": assessment, "evidence": payload["evidence"]}, separators=(",", ":")))
        except Exception as err:  # keep the report, but treat it as unchecked
            check, vmeta = {"supported": False, "note": f"Verifier could not run: {err}"}, {}
            report.guardrail_notes.append("Verifier unavailable; report treated as unverified.")
        check = summarize_verification(check)
        report.verification = check
        for k in ("calls", "latency_s", "prompt_tokens", "completion_tokens"):
            meta[k] = meta.get(k, 0) + vmeta.get(k, 0)
        if check.get("supported") is not True:
            flagged = len(check.get("unsupported_claims") or []) + len(check.get("invented_values") or []) \
                + len(check.get("safety_issues") or [])
            if flagged:
                report.guardrail_notes.append(
                    f"Verifier flagged {flagged} claim(s); confidence capped at 0.5. See Checks for details.")
            report.confidence = min(report.confidence, 0.5)
            report = apply_guardrails(report, assessment, {e["id"] for e in evidence})
        step("Check passed: every claim is backed by the evidence or the detector."
             if check.get("supported") is True else "Check found problems; see Checks below.")
    return report, evidence, meta
