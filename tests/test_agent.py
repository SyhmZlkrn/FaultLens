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


def test_extract_json_ignores_trailing_text_and_orphan_think_close():
    assert extract_json('reasoning here</think>{"a": {"b": 2}} done. {"c": 3}') == {"a": {"b": 2}}


def test_must_have_sections_kept_even_when_cut_by_k():
    class ManualFirst(FakeRetriever):
        def search(self, query, k=4, source=None):
            pool = [c for c in self.chunks if source is None or c["source"] == source]
            if source == "manual":  # MAN-09 and MAN-10 rank first, then get cut by k_manual=1
                pool = sorted(pool, key=lambda c: c["id"] not in ("MAN-09", "MAN-10"))
            return [{**c, "score": 0.5} for c in pool[:k]]

    from app.agent import gather_evidence
    ids = [e["id"] for e in gather_evidence(ManualFirst(), ASSESS, k_manual=1)]
    assert "MAN-09" in ids and "MAN-10" in ids
    assert len(ids) == len(set(ids))


def test_sloppy_model_output_is_normalized():
    sloppy = {"summary": "x", "severity": "Warning", "confidence": 80,
              "likely_causes": [{"cause": "fouling", "likelihood": "High", "citations": ["MAN-02"]}],
              "recommended_actions": [{"step": "wash", "priority": "Next shift", "citations": ["MAN-02"]}],
              "work_order": {"title": "Wash", "asset": "GT-07", "priority": "p2", "description": "d",
                             "estimated_downtime_hours": "9"}}
    from app.agent import normalize_raw
    r = Report.model_validate(normalize_raw(sloppy))
    assert r.severity == "warning" and r.confidence == 0.8
    assert r.likely_causes[0].likelihood == "high"
    assert r.recommended_actions[0].priority == "next_shift"
    assert r.work_order.priority == "P2" and r.work_order.estimated_downtime_hours == 9.0


def test_verifier_failure_keeps_report_but_marks_unverified():
    calls = []

    def flaky_llm(system, user):
        calls.append(1)
        if len(calls) == 1:
            return ({"summary": "Fouling likely.", "severity": "warning", "confidence": 0.9,
                     "likely_causes": [{"cause": "fouling", "citations": ["MAN-02"]}],
                     "recommended_actions": [{"step": "check filters", "citations": ["MAN-02"]}]},
                    {"calls": 1, "latency_s": 0.1})
        raise RuntimeError("Model did not return valid JSON")

    report, _, _ = diagnose({**ASSESS, "severity": "warning"}, FakeRetriever(), llm_fn=flaky_llm)
    assert report.verification["supported"] is False
    assert report.confidence <= 0.5 and report.escalate


def test_busy_model_falls_back_to_next_token_factory_model(monkeypatch):
    import httpx
    from openai import RateLimitError

    from app import config, llm

    class FakeCompletions:
        def __init__(self):
            self.models = []

        def create(self, model, **kw):
            self.models.append(model)
            if model == "busy-model":
                resp = httpx.Response(429, request=httpx.Request("POST", "http://x"))
                raise RateLimitError("busy", response=resp, body=None)

            class R:
                usage = None
                choices = [type("C", (), {"message": type("M", (), {"content": '{"ok": true}'})()})()]
            return R()

    fake = FakeCompletions()
    monkeypatch.setattr(config, "AMD_MODEL", "busy-model")
    monkeypatch.setattr(config, "AMD_FALLBACK_MODELS", ["spare-model"])
    monkeypatch.setattr(llm, "client", lambda: type("Cl", (), {"chat": type("Ch", (), {"completions": fake})()})())
    out, meta = llm.chat_json("sys", "user")
    assert out == {"ok": True}
    assert fake.models == ["busy-model", "spare-model"] and meta["model"] == "spare-model"
