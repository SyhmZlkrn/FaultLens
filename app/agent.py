"""The diagnosis agent.

Pipeline: detector output -> retrieve evidence -> diagnose (LLM on AMD Token Factory) ->
enforce rules in code -> verify (second LLM pass) -> draft work order for human approval.

The LLM proposes. Code enforces the safety rules. A person approves.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Literal, Optional

from pydantic import BaseModel, Field

from app import config
from app.sensors import asset_name

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


def _clean(value, default: str, allowed: set[str], aliases: dict[str, str]) -> str:
    v = str(value or "").strip().lower()
    v = aliases.get(v, v)
    return v if v in allowed else default


def normalize_raw(raw: dict) -> dict:
    """Fix the small format slips open-weight models make ("High", "next shift", 80 for 0.8).

    Only formatting is changed here. The safety rules still run afterwards in apply_guardrails.
    """
    raw = dict(raw)
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
            c["citations"] = [str(x) for x in c.get("citations") or []]
            c["evidence"] = [str(x) for x in c.get("evidence") or []]
            causes.append(c)
    raw["likely_causes"] = causes
    actions = []
    for a in raw["recommended_actions"]:
        if isinstance(a, dict) and a.get("step"):
            a = {**a, "priority": _clean(a.get("priority"), "next_shift",
                                         {"immediate", "next_shift", "planned"}, _ACTION_PRIORITY)}
            a["citations"] = [str(x) for x in a.get("citations") or []]
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


def diagnose(assessment: dict, retriever, llm_fn: LLMFn | None = None, verify: bool = True) -> tuple[Report, list[dict], dict]:
    """Returns (report, evidence, llm_meta)."""
    if llm_fn is None:
        from app.llm import chat_json as llm_fn

    if assessment["severity"] == "normal":
        return Report(summary="Unit operating within its learned healthy pattern. No action needed.",
                      severity="normal", confidence=0.9), [], {}

    evidence = gather_evidence(retriever, assessment)
    payload = {
        "asset": {"id": asset_name(assessment["unit"]), "type": "Gas turbine (simulated)",
                  "current_cycle": assessment["cycle"]},
        "detector": assessment,
        "evidence": [{"id": e["id"], "source": e["source"], "title": e["title"], "text": e["text"]}
                     for e in evidence],
    }
    raw, meta = llm_fn(SYSTEM_PROMPT, json.dumps(payload, indent=2))
    report = Report.model_validate(normalize_raw(raw))
    report = apply_guardrails(report, assessment, {e["id"] for e in evidence})

    if verify:
        try:
            check, vmeta = llm_fn(VERIFIER_PROMPT, json.dumps(
                {"report": report.model_dump(exclude={"verification", "guardrail_notes"}),
                 "evidence": payload["evidence"]}, indent=2))
        except Exception as err:  # keep the report, but treat it as unchecked
            check, vmeta = {"supported": False, "note": f"Verifier could not run: {err}"}, {}
            report.guardrail_notes.append("Verifier unavailable; report treated as unverified.")
        report.verification = check
        for k in ("calls", "latency_s", "prompt_tokens", "completion_tokens"):
            meta[k] = meta.get(k, 0) + vmeta.get(k, 0)
        if check.get("supported") is not True:
            report.confidence = min(report.confidence, 0.5)
            report = apply_guardrails(report, assessment, {e["id"] for e in evidence})
    return report, evidence, meta
