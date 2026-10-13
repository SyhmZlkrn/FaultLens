"""Pure-Python tests: no GPU, no network. Run with `pytest -q` from the repo root."""
import numpy as np

from amd.build_index import incident_chunks, manual_chunks
from app.agent import Report, apply_guardrails, diagnose
from app.llm import extract_json

ASSESS = {"unit": 7, "cycle": 180, "anomaly_ratio": 2.4, "predicted_rul_cycles": 22.0,
          "severity": "critical",
          "top_sensors": [{"sensor": "s3", "code": "T30", "label": "T30 (Total temperature at HPC outlet)",
                           "unit": "degR", "anomaly_z": 5.1, "value_now": 1600.2,
                           "change_over_window": 2.1, "direction": "rising"}]}


def make_report(**kw):
    base = {"summary": "x", "severity": "warning", "confidence": 0.9,
            "likely_causes": [{"cause": "fouling", "citations": ["MAN-02", "MAN-99"]}],
            "recommended_actions": [{"step": "wash", "citations": ["MAN-02"]}],
            "work_order": {"title": "Wash", "asset": "wrong", "priority": "P3", "description": "d"}}
    base.update(kw)
    return Report.model_validate(base)


def test_invented_citations_are_removed():
    r = apply_guardrails(make_report(), ASSESS, {"MAN-02"})
    assert r.likely_causes[0].citations == ["MAN-02"]


def test_severity_never_lowered_and_critical_escalates():
    r = apply_guardrails(make_report(), ASSESS, {"MAN-02"})
    assert r.severity == "critical"
    assert r.escalate is True
    assert r.work_order.priority == "P1"
    assert r.work_order.asset == "GT-07"


def test_low_confidence_escalates():
    a = {**ASSESS, "severity": "warning"}
    r = apply_guardrails(make_report(confidence=0.4), a, {"MAN-02"})
    assert r.escalate and "confidence" in r.escalation_reason


def test_extract_json_handles_fences_and_think():
    assert extract_json('<think>hmm</think>```json\n{"a": 1}\n```') == {"a": 1}


def test_knowledge_parses():
    ids = {c["id"] for c in manual_chunks() + incident_chunks()}
    assert {"MAN-01", "MAN-09", "MAN-10", "INC-2025-004"} <= ids


class FakeRetriever:
    def __init__(self):
        self.chunks = manual_chunks() + incident_chunks()

    def search(self, query, k=4, source=None):
        pool = [c for c in self.chunks if source is None or c["source"] == source]
        return [{**c, "score": 0.5} for c in pool[:k]]


def test_diagnose_end_to_end_with_fake_llm():
    calls = []

    def fake_llm(system, user):
        calls.append(system[:20])
        if len(calls) == 1:
            return ({"summary": "Fouling likely.", "severity": "warning", "confidence": 0.8,
                     "likely_causes": [{"cause": "fouling", "citations": ["MAN-02"]}],
                     "recommended_actions": [{"step": "check filters", "citations": ["MAN-02"]}],
                     "work_order": {"title": "Wash", "asset": "GT-07", "priority": "P2", "description": "d"}},
                    {"calls": 1, "latency_s": 0.1})
        return {"supported": False, "unsupported_claims": ["x"]}, {"calls": 1, "latency_s": 0.1}

    report, evidence, meta = diagnose(ASSESS, FakeRetriever(), llm_fn=fake_llm)
    assert len(calls) == 2 and meta["calls"] == 2
    assert report.confidence <= 0.5 and report.escalate
    assert any(e["id"] == "MAN-09" for e in evidence)
