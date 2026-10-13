"""FaultLens operator UI.   streamlit run app/ui.py"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from app import config
from app.agent import diagnose
from app.detector import Detector
from app.retriever import Retriever
from app.sensors import asset_name

st.set_page_config(page_title="FaultLens", layout="wide")
SEV_COLOR = {"normal": "green", "warning": "orange", "critical": "red"}


@st.cache_resource
def load():
    return Detector(), Retriever(), pd.read_csv(config.DEMO_DATA)


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def fail(message: str):
    """Show a plain message with a retry button instead of a stack trace."""
    st.error(message)
    if st.button("Try again"):
        st.cache_resource.clear()
        st.rerun()
    st.stop()


try:
    detector, retriever, demo = load()
except Exception as err:  # missing or broken artifacts must not crash the demo
    fail(f"FaultLens could not load its model files ({type(err).__name__}: {err}). "
         "Check that artifacts/ and data/demo/ are present, then try again.")

# ---------- sidebar ----------
with st.sidebar:
    st.title("FaultLens")
    st.caption("Maintenance copilot for gas turbine units")
    units = sorted(demo["unit"].unique())
    unit = st.selectbox("Asset", units, format_func=asset_name)
    g = demo[demo["unit"] == unit].sort_values("cycle")
    cycle = st.slider("Replay to cycle", int(g["cycle"].min()) + 29, int(g["cycle"].max()),
                      int(g["cycle"].max()) - 40)

    st.divider()
    st.subheader("Running on AMD")
    m, b = read_json(config.METRICS_PATH), read_json(config.LLM_BENCH_PATH)
    st.markdown(
        f"- Detector trained on **{m.get('device', '?')}** (ROCm) in {m.get('train_seconds', '?')} s\n"
        f"- RUL test RMSE: {m.get('test_rul_rmse', '?')} cycles\n"
        f"- Reasoning model: **{config.AMD_MODEL or 'not set'}** via AMD Token Factory\n"
        f"- Median latency: {b.get('median_latency_s', '?')} s, {b.get('median_tokens_per_s', '?')} tok/s"
    )

history = g[g["cycle"] <= cycle]
try:
    a = detector.assess(history)
except Exception as err:
    fail(f"The detector could not assess {asset_name(unit)} at cycle {cycle} ({err}). "
         "Try another cycle or asset.")

# ---------- detector ----------
st.header(f"{asset_name(unit)} at cycle {cycle}")
c1, c2, c3 = st.columns(3)
c1.metric("Status", a["severity"].upper())
c2.metric("Anomaly ratio", a["anomaly_ratio"], help="Above 1.0 is outside the learned healthy range")
c3.metric("Predicted remaining life", f"{a['predicted_rul_cycles']:.0f} cycles")

top = [s["sensor"] for s in a["top_sensors"]]
chart = history.tail(80).set_index("cycle")[top]
chart.columns = [s["code"] for s in a["top_sensors"]]
st.line_chart(chart)
st.caption("Most abnormal sensors: " + ", ".join(
    f"{s['label']} {s['direction']} ({s['change_over_window']:+} {s['unit']})" for s in a["top_sensors"]))

# ---------- diagnosis ----------
if st.button("Diagnose", type="primary", disabled=a["severity"] == "normal"):
    with st.spinner("Retrieving manuals and incidents, reasoning on AMD..."):
        try:
            st.session_state.result = diagnose(a, retriever)
            st.session_state.result_key = (unit, cycle)
        except Exception as err:  # show the problem, keep the app alive for the demo
            st.error(f"Diagnosis could not finish: {err}. Check the AMD endpoint settings and try again.")

res = st.session_state.get("result")
if res and st.session_state.get("result_key") == (unit, cycle):
    report, evidence, meta = res
    st.subheader("Diagnosis")
    st.markdown(f":{SEV_COLOR[report.severity]}[**{report.severity.upper()}**]  "
                f"confidence {report.confidence:.0%}")
    st.write(report.summary)
    if report.escalate:
        st.warning(f"Escalate to reliability engineer: {report.escalation_reason}")

    left, right = st.columns(2)
    with left:
        st.markdown("**Likely causes**")
        for c in report.likely_causes:
            st.markdown(f"- **{c.cause}** ({c.likelihood}) [{', '.join(c.citations)}]")
            for e in c.evidence:
                st.caption(f"  {e}")
    with right:
        st.markdown("**Recommended actions**")
        for i, act in enumerate(report.recommended_actions, 1):
            st.markdown(f"{i}. {act.step} `{act.priority}` [{', '.join(act.citations)}]")
    if report.uncertainties:
        st.markdown("**Uncertain about**")
        for u in report.uncertainties:
            st.caption(f"- {u}")

    with st.expander("Evidence used"):
        for e in evidence:
            st.markdown(f"**{e['id']}** {e['title']}")
            st.caption(e["text"])
    with st.expander("Checks"):
        st.json({"verifier": report.verification, "guardrails": report.guardrail_notes, "llm": meta})

    # ---------- human approval ----------
    if report.work_order:
        st.subheader("Draft work order")
        wo = report.work_order
        title = st.text_input("Title", wo.title)
        prio = st.selectbox("Priority", ["P1", "P2", "P3"], index=["P1", "P2", "P3"].index(wo.priority))
        desc = st.text_area("Description", wo.description, height=140)
        approver = st.text_input("Approved by")
        a1, a2 = st.columns(2)
        if a1.button("Approve and raise work order", disabled=not approver):
            config.WORKORDERS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(config.WORKORDERS_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps({"asset": wo.asset, "title": title, "priority": prio,
                                    "description": desc, "approved_by": approver,
                                    "at": datetime.now(timezone.utc).isoformat()}) + "\n")
            st.success(f"Work order raised for {wo.asset}.")
        if a2.button("Reject"):
            st.info("Draft discarded. Nothing was raised.")
