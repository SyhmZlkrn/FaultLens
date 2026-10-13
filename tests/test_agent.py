"""Pure-Python tests: no GPU, no network. Run with `pytest -q` from the repo root."""
import json

import numpy as np

from scripts.build_index import incident_chunks, manual_chunks
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


def test_trend_ignores_single_noisy_endpoints():
    from app.data import trend
    rng = np.random.default_rng(0)
    rising = np.linspace(0, 10, 30) + rng.normal(0, 1, 30)
    rising[-1] = -5.0  # one bad last reading must not flip the direction
    change, direction = trend(rising)
    assert direction == "rising" and change > 5
    assert trend(rng.normal(0, 1, 30))[1] == "steady"


def test_diagnose_reports_progress_steps():
    steps = []

    def fake_llm(system, user):
        if "strict reviewer" in system:
            return {"supported": True}, {"calls": 1, "latency_s": 0.1}
        return ({"summary": "s", "severity": "warning", "confidence": 0.8,
                 "likely_causes": [{"cause": "fouling", "citations": ["MAN-02"]}]},
                {"calls": 1, "latency_s": 0.1, "model": "fake-model"})

    diagnose({**ASSESS, "severity": "warning"}, FakeRetriever(), llm_fn=fake_llm, on_step=steps.append)
    assert len(steps) == 5 and "fake-model" in steps[2]


def test_verifier_sees_detector_observations():
    seen = {}

    def fake_llm(system, user):
        if "strict reviewer" in system:
            seen.update(json.loads(user))
            return {"supported": True}, {"calls": 1, "latency_s": 0.1}
        return ({"summary": "s", "severity": "warning", "confidence": 0.8,
                 "likely_causes": [{"cause": "fouling", "citations": ["MAN-02"]}]},
                {"calls": 1, "latency_s": 0.1})

    diagnose({**ASSESS, "severity": "warning"}, FakeRetriever(), llm_fn=fake_llm)
    assert seen["detector"]["top_sensors"][0]["code"] == "T30"


def test_verifier_verdict_comes_from_failed_checks_only():
    from app.agent import summarize_verification
    fine = summarize_verification({"checks": [
        {"claim": "Nc rose 29.4 rpm", "ok": True, "issue": None, "reason": "in detector"},
        {"claim": "wash per MAN-02", "ok": True, "issue": None, "reason": "MAN-02 says so"}], "note": "ok"})
    assert fine["supported"] is True and fine["unsupported_claims"] == [] and fine["checked"] == 2
    bad = summarize_verification({"checks": [
        {"claim": "a", "ok": True},
        {"claim": "escalate on wear metals", "ok": False, "issue": "unsupported", "reason": "not in MAN-09"},
        {"claim": "torque 40 Nm", "ok": False, "issue": "invented", "reason": "no such value"}]})
    assert bad["supported"] is False
    assert len(bad["unsupported_claims"]) == 1 and len(bad["invented_values"]) == 1


def test_verifier_rejection_leaves_a_note():
    def fake_llm(system, user):
        if "strict reviewer" in system:
            return {"checks": [{"claim": "x", "ok": False, "issue": "unsupported", "reason": "r"}]}, {"calls": 1}
        return ({"summary": "s", "severity": "warning", "confidence": 0.9,
                 "likely_causes": [{"cause": "fouling", "citations": ["MAN-02"]}]}, {"calls": 1})

    report, _, _ = diagnose({**ASSESS, "severity": "warning"}, FakeRetriever(), llm_fn=fake_llm)
    assert report.confidence == 0.5 and any("Verifier flagged 1" in n for n in report.guardrail_notes)


def test_citations_recovered_from_text_when_list_is_empty():
    from app.agent import normalize_raw
    raw = normalize_raw({"summary": "s", "severity": "warning", "confidence": 0.7,
                         "likely_causes": [{"cause": "Fouling (MAN-02 signature)", "citations": []},
                                           {"cause": "Bearing", "citations": "MAN-05, INC-2026-014"}],
                         "recommended_actions": [{"step": "Wash per MAN-02", "citations": None}]})
    assert raw["likely_causes"][0]["citations"] == ["MAN-02"]
    assert raw["likely_causes"][1]["citations"] == ["MAN-05", "INC-2026-014"]
    assert raw["recommended_actions"][0]["citations"] == ["MAN-02"]


SPEED_CASE = {"severity": "warning", "top_sensors": [
    {"code": "NRc", "direction": "rising", "change_over_window": 27.22, "value_now": 8173.21},
    {"code": "Nc", "direction": "rising", "change_over_window": 29.428, "value_now": 9104.22},
    {"code": "T30", "direction": "steady", "change_over_window": -0.077, "value_now": 1588.04}]}


def test_sensor_check_catches_renamed_sensor():
    from app.checks import check_sensor_claims
    problems = check_sensor_claims(["Nf (fan speed) rose 27.2 rpm over 30 cycles"], SPEED_CASE)
    assert problems and "Nf" in problems[0]


def test_sensor_check_catches_wrong_direction_and_number():
    from app.checks import check_sensor_claims
    assert check_sensor_claims(["T30 rising over the window"], SPEED_CASE)
    assert check_sensor_claims(["Nc rose 45.0 rpm over 30 cycles"], SPEED_CASE)


def test_sensor_check_accepts_correct_observations():
    from app.checks import check_sensor_claims
    good = ["Core speed (Nc, NRc) is drifting upward with T30 steady.",
            "Nc and NRc rising over 30 cycles (29.4 and 27.2 rpm)",
            "T30 (HPC outlet temperature) steady at 1588 degR, change -0.08 degR",
            "If T50 rises after the wash, request a borescope.",
            "Check P30 and Ps30 trends to confirm.",
            "T50 is not rising yet."]
    assert check_sensor_claims(good, SPEED_CASE) == []


def test_sensor_check_uses_all_sensors_when_present():
    from app.checks import check_sensor_claims
    full = {**SPEED_CASE, "all_sensors": [*SPEED_CASE["top_sensors"],
            {"code": "P30", "direction": "steady", "change_over_window": 0.01, "value_now": 553.1}]}
    assert check_sensor_claims(["P30 steady"], full) == []
    assert check_sensor_claims(["P30 falling"], full)


def test_sensor_check_no_false_alarms_from_baseline_run():
    from app.checks import check_sensor_claims
    case = {"top_sensors": [
        {"code": "phi", "direction": "falling", "change_over_window": -0.2, "value_now": 520.9},
        {"code": "Nf", "direction": "rising", "change_over_window": 0.05, "value_now": 2388.2},
        {"code": "NRf", "direction": "rising", "change_over_window": 0.04, "value_now": 8136.1}]}
    assert check_sensor_claims(["phi (fuel flow to Ps30 ratio) is falling, suggesting hot section wear"], case) == []
    assert check_sensor_claims(["Critical anomaly with falling phi and rising fan speeds"], case) == []
    assert check_sensor_claims(["rising phi with steady fan speed"], case)  # still catches a real reversal


def test_sensor_check_handles_lists_comparisons_and_small_changes():
    from app.checks import check_sensor_claims
    case = {"all_sensors": [
        {"code": "T24", "direction": "rising", "change_over_window": 0.5, "value_now": 643.0},
        {"code": "T50", "direction": "rising", "change_over_window": 7.5, "value_now": 1420.0},
        {"code": "P30", "direction": "falling", "change_over_window": -0.49, "value_now": 552.0},
        {"code": "T30", "direction": "rising", "change_over_window": 5.1, "value_now": 1597.0},
        {"code": "phi", "direction": "falling", "change_over_window": -0.3, "value_now": 520.0},
        {"code": "Ps30", "direction": "steady", "change_over_window": 0.077, "value_now": 48.1}]}
    assert check_sensor_claims(["HPC pattern with rising T24/T50, falling P30"], case) == []
    assert check_sensor_claims(["T50 is rising faster than T30 (HPC outlet temperature) with a widening "
                                "exhaust spread, and phi (fuel flow to Ps30 ratio) is falling"], case) == []
    assert check_sensor_claims(["P30 fell 0.489 psia while Ps30 rose 0.077 psia"], case) == []
    assert check_sensor_claims(["Ps30 fell slightly"], case)  # wrong sign is still caught
    assert check_sensor_claims(["T30 steady"], case)  # calling a moving sensor steady is caught


def test_glitch_suffix_is_repaired_only_on_codes_and_direction_words():
    from app.agent import normalize_raw
    raw = normalize_raw({"summary": "T30 steadyaine, rising Ps30ainer; check the container.",
                         "severity": "warning", "confidence": 0.7})
    assert raw["summary"] == "T30 steady, rising Ps30; check the container."
