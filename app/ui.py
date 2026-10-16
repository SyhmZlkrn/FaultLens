"""FaultLens operator UI.   streamlit run app/ui.py

Design: a calm, light operations console. One reserved status colour (green / amber / red)
encodes unit health and nothing else; every chart shares one technical accent. See the
design notes in docs/design.md.
"""
try:
    import fcntl
except ImportError:
    fcntl = None  # fallback for environments without fcntl (e.g. Windows)
import html
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import altair as alt
import pandas as pd
import streamlit as st

from app import config
from app.agent import diagnose
from app.detector import Detector
from app.retriever import Retriever
from app.sensors import asset_name

st.set_page_config(page_title="FaultLens", layout="wide", initial_sidebar_state="expanded")

DEMO_UNIT = 97  # cleanest replay: normal, then warning at cycle 149, critical at 176

# ---------- design tokens ----------
INK, INK2, INK3 = "#0F172A", "#475569", "#64748B"
ACCENT, LINE = "#0E7490", "#E3E8EF"
SEV = {
    "normal":   {"c": "#15803D", "bg": "#ECFDF3", "label": "Normal"},
    "warning":  {"c": "#B45309", "bg": "#FFF7ED", "label": "Warning"},
    "critical": {"c": "#B91C1C", "bg": "#FEF2F2", "label": "Critical"},
}
PRIO = {"immediate": "#B91C1C", "next_shift": "#B45309", "planned": "#0E7490"}
PRIO_LABEL = {"immediate": "Immediate", "next_shift": "Next shift", "planned": "Planned"}
ARROW = {"rising": "▲", "falling": "▼", "steady": "▬"}

LOGO = (
    '<svg class="fl-logo" viewBox="0 0 28 28" fill="none" aria-hidden="true">'
    '<circle cx="14" cy="14" r="12.5" stroke="#0E7490" stroke-width="1.6"/>'
    '<path d="M6 15.5h3.4l2.1-5 3.1 9 2.3-6 1.4 2h3.7" stroke="#0E7490" stroke-width="1.7" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
)
WARN_ICON = (
    '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden="true" '
    'style="flex:none;margin-top:2px">'
    '<path d="M12 3.6 22 20H2L12 3.6Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>'
    '<path d="M12 10v4.4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>'
    '<circle cx="12" cy="17.3" r="0.95" fill="currentColor"/></svg>'
)

CSS = f"""
:root {{
  --bg:#F1F4F8; --surface:#FFFFFF; --surface-2:#F7F9FC; --line:{LINE}; --line-2:#EDF1F6;
  --ink:{INK}; --ink-2:{INK2}; --ink-3:{INK3}; --accent:{ACCENT};
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,system-ui,"Helvetica Neue",Arial,sans-serif;
  --mono:ui-monospace,"SF Mono","JetBrains Mono","Cascadia Code",Menlo,monospace;
}}
html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stSidebar"],
[data-testid="stMarkdownContainer"], .stApp p, .stApp h1, .stApp h2, .stApp h3, .stApp h4,
.stApp label, .stApp li, .stApp td, .stApp th, .stApp input, .stApp textarea, .stApp select
  {{ font-family: var(--sans); }}
.stApp {{ background: var(--bg); }}
[data-testid="stHeader"] {{ background: transparent; }}
.block-container {{ padding-top: 1.1rem; padding-bottom: 4rem; max-width: 1240px; }}

/* sidebar */
[data-testid="stSidebar"] {{ background: var(--surface); border-right: 1px solid var(--line); }}
[data-testid="stSidebar"] .block-container {{ padding-top: 1.4rem; }}
[data-testid="stSidebar"] hr {{ margin: 18px 0; border-color: var(--line-2); }}

/* headings */
h1,h2,h3,h4 {{ color: var(--ink); letter-spacing: -0.01em; }}
.fl-topbar {{ display:flex; align-items:center; justify-content:space-between; gap:16px;
  padding-bottom:14px; border-bottom:1px solid var(--line); margin-bottom:20px; }}
.fl-brand {{ display:flex; align-items:center; gap:11px; }}
.fl-logo {{ width:28px; height:28px; flex:none; }}
.fl-brand-name {{ font-size:16.5px; font-weight:700; color:var(--ink); letter-spacing:-0.02em; line-height:1.1; }}
.fl-brand-sub {{ font-size:12px; color:var(--ink-3); margin-top:2px; }}
.fl-ramp {{ display:flex; align-items:center; gap:8px; font-size:12px; color:var(--ink-3);
  background:var(--surface-2); border:1px solid var(--line); border-radius:999px; padding:6px 13px; }}
.fl-ramp b {{ color:var(--ink-2); font-weight:600; }}
.fl-ramp .pulse {{ width:7px; height:7px; border-radius:50%; background:var(--accent); }}

.fl-pagehead {{ display:flex; align-items:flex-end; justify-content:space-between; gap:16px; margin:2px 0 4px; }}
.fl-eyebrow {{ font-size:11px; font-weight:650; letter-spacing:.1em; text-transform:uppercase; color:var(--ink-3); }}
.fl-h1 {{ font-size:30px; font-weight:680; letter-spacing:-0.025em; color:var(--ink); margin:4px 0 0; line-height:1.05; }}
.fl-h1 .mono {{ font-family:var(--mono); }}
.fl-h1 .cyc {{ color:var(--ink-3); font-weight:500; }}
.fl-chip {{ display:inline-flex; align-items:center; gap:8px; padding:7px 14px; border-radius:999px;
  font-size:12.5px; font-weight:650; letter-spacing:.02em; color:var(--sev); background:var(--sev-bg);
  border:1px solid color-mix(in srgb, var(--sev) 22%, transparent); white-space:nowrap; margin-bottom:6px; }}
.fl-chip .dot {{ width:9px; height:9px; border-radius:50%; background:var(--sev); }}

/* health cluster */
.fl-gauge {{ display:flex; background:var(--surface); border:1px solid var(--line);
  border-left:4px solid var(--sev); border-radius:14px; overflow:hidden; margin:16px 0 24px; }}
.fl-gauge .cell {{ flex:1 1 0; padding:15px 20px; min-width:0; }}
.fl-gauge .cell + .cell {{ border-left:1px solid var(--line-2); }}
.fl-gauge .v {{ font-size:29px; font-weight:660; letter-spacing:-.025em; color:var(--ink);
  font-variant-numeric:tabular-nums; margin-top:7px; display:flex; align-items:center; gap:10px; line-height:1.1; }}
.fl-gauge .cell.sev .v {{ color:var(--sev); }}
.fl-gauge .v .u {{ font-size:13px; font-weight:500; color:var(--ink-3); margin-left:2px; }}
.fl-gauge .dot {{ width:10px; height:10px; border-radius:50%; background:var(--sev); flex:none;
  box-shadow:0 0 0 4px var(--sev-bg); }}
.fl-gauge .sub {{ font-size:12px; color:var(--ink-3); margin-top:6px; }}

/* cards */
[data-testid="stVerticalBlockBorderWrapper"] {{ background:var(--surface); border:1px solid var(--line) !important;
  border-radius:14px; }}
.fl-sensor-head {{ display:flex; align-items:baseline; justify-content:space-between; gap:10px; margin-bottom:2px; }}
.fl-sensor-code {{ font-family:var(--mono); font-size:13px; font-weight:650; color:var(--ink); }}
.fl-sensor-label {{ font-size:12px; color:var(--ink-3); margin-top:2px; }}
.fl-delta {{ font-size:12px; font-variant-numeric:tabular-nums; color:var(--ink-2); white-space:nowrap; }}
.fl-delta .z {{ color:var(--ink-3); margin-left:8px; }}

/* report */
.fl-sec {{ font-size:11px; font-weight:650; letter-spacing:.1em; text-transform:uppercase; color:var(--ink-3); margin-bottom:10px; }}
.fl-summary {{ font-size:15.5px; line-height:1.6; color:var(--ink); }}
.fl-cite {{ display:inline-block; font-family:var(--mono); font-size:11.5px; font-weight:600; color:var(--accent);
  background:#ECF6F8; border:1px solid #D6E9EE; border-radius:6px; padding:2px 7px; margin-right:4px; }}
.fl-cite-none {{ color:#B45309; background:#FFF7ED; border-color:#F3DEC2; font-family:var(--sans); font-weight:600; }}
.fl-cause {{ border-top:1px solid var(--line-2); padding:11px 0 3px; }}
.fl-cause:first-child {{ border-top:none; padding-top:2px; }}
.fl-cause .t {{ font-weight:640; color:var(--ink); font-size:14px; }}
.fl-cause .l {{ font-size:11.5px; color:var(--ink-3); text-transform:uppercase; letter-spacing:.06em; font-weight:600; }}
.fl-cause .ev {{ font-size:12.5px; color:var(--ink-2); line-height:1.5; margin-top:5px; padding-left:12px;
  border-left:2px solid var(--line-2); }}
.fl-act {{ display:flex; gap:12px; padding:9px 0; border-top:1px solid var(--line-2); }}
.fl-act:first-child {{ border-top:none; padding-top:2px; }}
.fl-act .n {{ font-family:var(--mono); font-size:12px; color:var(--ink-3); padding-top:2px; min-width:14px; }}
.fl-act .s {{ font-size:14px; color:var(--ink); line-height:1.45; }}
.fl-prio {{ display:inline-flex; align-items:center; gap:6px; font-size:11px; font-weight:600; color:var(--ink-2);
  background:var(--surface-2); border:1px solid var(--line); border-radius:999px; padding:1px 9px 1px 7px; margin-left:8px; }}
.fl-prio .d {{ width:6px; height:6px; border-radius:50%; flex:none; }}
.fl-banner {{ display:flex; gap:11px; align-items:flex-start; border-radius:12px; padding:13px 16px; margin:14px 0;
  font-size:13.5px; line-height:1.5; border:1px solid color-mix(in srgb, var(--sev) 26%, transparent);
  background:var(--sev-bg); color:var(--ink); }}
.fl-banner b {{ color:var(--sev); }}
.fl-banner .ic {{ font-size:15px; line-height:1.4; }}
.fl-empty {{ border:1.5px dashed #D3DAE4; border-radius:14px; padding:26px 22px; text-align:center;
  background:var(--surface-2); color:var(--ink-3); font-size:13.5px; margin-top:8px; }}
.fl-empty b {{ color:var(--ink-2); display:block; margin-bottom:3px; font-size:14px; font-weight:620; }}
.fl-note {{ font-size:12.5px; color:var(--ink-3); line-height:1.55; }}
.fl-kv {{ display:flex; justify-content:space-between; gap:14px; font-size:12.5px; padding:6px 0;
  border-top:1px solid var(--line-2); }}
.fl-kv:first-child {{ border-top:none; }}
.fl-kv .k {{ color:var(--ink-3); }}
.fl-kv .v {{ color:var(--ink-2); font-variant-numeric:tabular-nums; text-align:right; }}

/* widgets */
.stButton > button {{ border-radius:9px; font-weight:600; border:1px solid var(--line); }}
.stButton > button[kind="primary"] {{ background:var(--accent); border-color:var(--accent); }}
.stButton > button[kind="primary"]:hover {{ background:#0B5C74; border-color:#0B5C74; }}
[data-testid="stExpander"] details {{ border-radius:12px; border:1px solid var(--line); background:var(--surface); }}
[data-testid="stExpander"] summary {{ font-size:13px; font-weight:600; color:var(--ink-2); }}
[data-baseweb="select"] > div, .stTextInput input, .stTextArea textarea {{ border-radius:9px !important; }}
.stSlider [data-baseweb="slider"] {{ margin-top: 4px; }}

@media (prefers-color-scheme: dark) {{
  :root {{
    --bg:#0B0F19; --surface:#131B28; --surface-2:#1A2436; --line:#243242; --line-2:#1E293B;
    --ink:#F8FAFC; --ink-2:#CBD5E1; --ink-3:#94A3B8; --accent:#38BDF8;
  }}
  .stApp {{ background: var(--bg); }}
  [data-testid="stSidebar"] {{ background: var(--surface); border-color: var(--line); }}
  [data-testid="stVerticalBlockBorderWrapper"] {{ background: var(--surface) !important; border-color: var(--line) !important; }}
  .fl-gauge {{ background: var(--surface); border-color: var(--line); }}
  .fl-ramp {{ background: var(--surface-2); border-color: var(--line); }}
  .fl-cite {{ background:#162B3A; border-color:#20485E; color:#38BDF8; }}
  .fl-cite-none {{ background:#3B2712; border-color:#5F3D18; color:#FBBF24; }}
  .fl-empty {{ background:var(--surface-2); border-color:#334155; }}
  [data-testid="stExpander"] details {{ background:var(--surface); border-color:var(--line); }}
  .stButton > button {{ background: var(--surface-2); color: var(--ink); border-color: var(--line); }}
}}
@media (prefers-reduced-motion: no-preference) {{
  .fl-gauge, .fl-chip, .fl-banner {{ transition: background-color .18s ease, border-color .18s ease; }}
}}
@media (max-width: 900px) {{
  .block-container {{ padding-left: 1rem; padding-right: 1rem; }}
  .fl-h1 {{ font-size: 24px; }}
  .fl-gauge {{ flex-direction: column; }}
  .fl-gauge .cell + .cell {{ border-left:none; border-top:1px solid var(--line-2); }}
}}
"""


# ---------- helpers ----------
def sev_style(severity: str) -> str:
    m = SEV.get(severity, SEV["warning"])
    return f'--sev:{m["c"]};--sev-bg:{m["bg"]}'


def cites(ids: list[str]) -> str:
    if not ids:
        return '<span class="fl-cite fl-cite-none">no citation</span>'
    return " ".join(f'<span class="fl-cite">{html.escape(str(i))}</span>' for i in ids)


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def sensor_chart(df: pd.DataFrame, s: dict) -> alt.Chart:
    """One sensor per chart with its own scale, so a small drift is visible. Quiet chrome."""
    nearest = alt.selection_point(nearest=True, on="mouseover", empty=False)
    base = alt.Chart(df).encode(
        x=alt.X("cycle:Q", title="cycle", axis=alt.Axis(
            labelColor=INK3, titleColor=INK3, labelFontSize=10, titleFontSize=10,
            grid=False, ticks=False, domainColor=LINE, format="d")),
        y=alt.Y(f"{s['sensor']}:Q", title=s["unit"], scale=alt.Scale(zero=False),
                axis=alt.Axis(labelColor=INK3, titleColor=INK3, labelFontSize=10,
                              titleFontSize=10, gridColor="#EDF1F6", domain=False, ticks=False,
                              tickCount=4)),
    )
    line = base.mark_line(strokeWidth=1.7, color=ACCENT, interpolate="monotone")
    points = base.mark_point(color=ACCENT, size=45, filled=True).encode(
        opacity=alt.condition(nearest, alt.value(1), alt.value(0)),
        tooltip=[alt.Tooltip("cycle:Q", title="cycle"),
                 alt.Tooltip(f"{s['sensor']}:Q", title=s["code"], format=".2f")],
    ).add_params(nearest)
    return (
        (line + points)
        .properties(height=150)
        .configure_view(stroke=None)
        .configure(background="transparent", padding={"left": 0, "right": 6, "top": 6, "bottom": 0})
    )


def fail(message: str):
    """Show a plain message with a retry button instead of a stack trace."""
    st.error(message)
    if st.button("Try again"):
        st.cache_resource.clear()
        st.rerun()
    st.stop()


@st.cache_resource
def load():
    return Detector(), Retriever(), pd.read_csv(config.DEMO_DATA)


st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)

try:
    detector, retriever, demo = load()
except Exception as err:  # missing or broken artifacts must not crash the demo
    fail(f"FaultLens could not load its model files ({type(err).__name__}: {err}). "
         "Check that artifacts/ and data/demo/ are present, then try again.")

# ---------- sidebar ----------
with st.sidebar:
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:2px">{LOGO}'
        '<div><div class="fl-brand-name">FaultLens</div>'
        '<div class="fl-brand-sub">Gas turbine maintenance copilot</div></div></div>',
        unsafe_allow_html=True)
    st.markdown('<div style="height:14px"></div>', unsafe_allow_html=True)

    units = sorted(demo["unit"].unique())
    default_unit = units.index(DEMO_UNIT) if DEMO_UNIT in units else 0
    unit = st.selectbox("Asset", units, index=default_unit, format_func=asset_name)
    g = demo[demo["unit"] == unit].sort_values("cycle")
    cycle = st.slider("Replay to cycle", int(g["cycle"].min()) + 29, int(g["cycle"].max()),
                      int(g["cycle"].max()) - 40,
                      help="Move the timeline to replay the unit through its life.")

    st.divider()
    st.markdown('<div class="fl-sec">Reasoning on AMD</div>', unsafe_allow_html=True)
    m, b = read_json(config.METRICS_PATH), read_json(config.LLM_BENCH_PATH)
    last = (st.session_state.get("result") or (None, None, {}))[2]
    rows = [("Runtime", config.AMD_MODEL or "not set")]
    if last.get("model"):
        rows.append(("Last answer", f'{last["model"]} · {last.get("latency_s", 0):.0f}s'))
    if b:
        rows.append(("Benchmark", f'{b.get("median_latency_s", "?")}s · {b.get("median_tokens_per_s", "?")} tok/s'))
    st.markdown(
        "".join(f'<div class="fl-kv"><span class="k">{k}</span><span class="v">{html.escape(str(v))}</span></div>'
                for k, v in rows),
        unsafe_allow_html=True)
    st.markdown('<div style="height:10px"></div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="fl-note">Diagnosis and the verifier run on <b>AMD Token Factory</b>. '
        + (f'If it is busy, calls fall back to {html.escape(", ".join(config.AMD_FALLBACK_MODELS))}. ' if config.AMD_FALLBACK_MODELS else '')
        + f'Detector: LSTM models trained on {m.get("device", "?")} in {m.get("train_seconds", "?")} s, '
        f'remaining-life test RMSE {m.get("test_rul_rmse", "?")} cycles (NASA C-MAPSS FD001).</div>',
        unsafe_allow_html=True)

history = g[g["cycle"] <= cycle]
try:
    a = detector.assess(history)
except Exception as err:
    fail(f"The detector could not assess {asset_name(unit)} at cycle {cycle} ({err}). "
         "Try another cycle or asset.")

# ---------- header ----------
st.markdown(
    f'<div class="fl-topbar"><div class="fl-brand">{LOGO}'
    '<div><div class="fl-brand-name">FaultLens</div>'
    '<div class="fl-brand-sub">Maintenance copilot · gas turbine fleet</div></div></div>'
    '<div class="fl-ramp"><span class="pulse"></span>Reasoning on <b>AMD Token Factory</b></div></div>',
    unsafe_allow_html=True)

sm = SEV[a["severity"]]
st.markdown(
    f'<div class="fl-pagehead">'
    f'<div><div class="fl-eyebrow">Gas turbine unit</div>'
    f'<h1 class="fl-h1"><span class="mono">{html.escape(asset_name(unit))}</span> '
    f'<span class="cyc">· cycle {cycle}</span></h1></div></div>',
    unsafe_allow_html=True)

# ---------- health cluster ----------
rul = a["predicted_rul_cycles"]
ratio = a["anomaly_ratio"]
st.markdown(
    f'<div class="fl-gauge" style="{sev_style(a["severity"])}">'
    f'<div class="cell sev"><div class="fl-eyebrow">Status</div>'
    f'<div class="v"><span class="dot"></span>{sm["label"].upper()}</div>'
    f'<div class="sub">Detector verdict at this cycle</div></div>'
    f'<div class="cell"><div class="fl-eyebrow">Anomaly ratio</div>'
    f'<div class="v">{ratio:.2f}</div>'
    f'<div class="sub">1.0 is the healthy edge</div></div>'
    f'<div class="cell"><div class="fl-eyebrow">Predicted remaining life</div>'
    f'<div class="v">{rul:.0f}<span class="u">cycles</span></div>'
    f'<div class="sub">Warns below 60, critical below 30</div></div>'
    f'</div>',
    unsafe_allow_html=True)

# ---------- sensor trends ----------
st.markdown('<div class="fl-sec">Most abnormal sensors</div>', unsafe_allow_html=True)
recent = history.tail(80)
cols = st.columns(len(a["top_sensors"]))
for col, s in zip(cols, a["top_sensors"]):
    with col:
        with st.container(border=True):
            sign = f"{s['change_over_window']:+g}"
            st.markdown(
                f'<div class="fl-sensor-head"><span class="fl-sensor-code">{html.escape(s["code"])}</span>'
                f'<span class="fl-delta">{ARROW.get(s["direction"], "")} {sign} {html.escape(s["unit"])}'
                f'<span class="z">z {s["anomaly_z"]}</span></span></div>'
                f'<div class="fl-sensor-label">{html.escape(s["label"])} · {s["direction"]}</div>',
                unsafe_allow_html=True)
            st.altair_chart(sensor_chart(recent, s), width="stretch")

# ---------- diagnose ----------
st.markdown('<div style="height:6px"></div>', unsafe_allow_html=True)
is_normal = a["severity"] == "normal"
is_diagnosing = st.session_state.get("is_diagnosing", False)

# In-memory diagnosis cache across inspected cycles (instant reload on revisiting cycles)
diag_cache = st.session_state.setdefault("diagnosis_cache", {})
cached_entry = diag_cache.get((unit, cycle))
if cached_entry and st.session_state.get("result_key") != (unit, cycle):
    st.session_state.result = cached_entry
    st.session_state.result_key = (unit, cycle)

btn_label = "Re-diagnose" if cached_entry else "Diagnose"
btn_help = "Re-runs the diagnosis on AMD Token Factory." if cached_entry else "Runs the diagnosis agent and the verifier on AMD Token Factory."

if st.button(btn_label, type="primary" if not cached_entry else "secondary", disabled=(is_normal or is_diagnosing),
             help=btn_help):
    st.session_state.is_diagnosing = True
    st.session_state.discarded_order = None
    started = time.perf_counter()
    with st.status("Diagnosing", expanded=True) as status:
        try:
            res = diagnose(a, retriever, on_step=status.write)
            st.session_state.result = res
            st.session_state.result_key = (unit, cycle)
            if len(st.session_state.diagnosis_cache) >= 25:
                st.session_state.diagnosis_cache.pop(next(iter(st.session_state.diagnosis_cache)))
            st.session_state.diagnosis_cache[(unit, cycle)] = res
            status.update(label=f"Diagnosis ready in {time.perf_counter() - started:.0f} s",
                          state="complete", expanded=False)
        except Exception as err:  # show the problem, keep the app alive for the demo
            status.update(label="Diagnosis could not finish", state="error")
            st.error(f"Diagnosis could not finish: {err}. Press Diagnose to try again.")
        finally:
            st.session_state.is_diagnosing = False

if is_normal:
    st.markdown(
        '<div class="fl-empty"><b>Within its healthy pattern</b>'
        'Nothing to diagnose at this cycle. Move the replay forward and diagnose again when the '
        'detector raises the unit to Warning or Critical.</div>',
        unsafe_allow_html=True)

# ---------- diagnosis report ----------
res = st.session_state.get("result")
if res and st.session_state.get("result_key") == (unit, cycle):
    report, evidence, meta = res
    rm = SEV[report.severity]
    st.markdown('<div style="height:20px"></div><div class="fl-sec">Diagnosis</div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(
            f'<div style="{sev_style(report.severity)};display:flex;align-items:center;gap:12px;margin-bottom:12px;flex-wrap:wrap;">'
            f'<span class="fl-chip" style="{sev_style(report.severity)}"><span class="dot"></span>{rm["label"].upper()}</span>'
            f'<span class="fl-note">model confidence <b style="color:var(--ink-2)">{report.confidence:.0%}</b>'
            + (f' · answered by {html.escape(str(meta.get("model", "")))} in {meta.get("latency_s", 0):.0f}s' if meta.get("model") else '')
            + '</span></div>'
            f'<div class="fl-summary">{html.escape(report.summary)}</div>',
            unsafe_allow_html=True)
        if report.escalate:
            st.markdown(
                f'<div class="fl-banner" style="{sev_style("critical")}" role="status">'
                f'<span style="color:var(--sev);display:flex">{WARN_ICON}</span>'
                f'<div><b>Escalate to a reliability engineer.</b> '
                f'{html.escape(report.escalation_reason or "")}</div></div>',
                unsafe_allow_html=True)

    left, right = st.columns(2, gap="medium")
    with left:
        with st.container(border=True):
            st.markdown('<div class="fl-sec">Likely causes</div>', unsafe_allow_html=True)
            if not report.likely_causes:
                st.markdown('<div class="fl-note">No causes reported.</div>', unsafe_allow_html=True)
            for c in report.likely_causes:
                ev = "".join(f'<div class="ev">{html.escape(str(e))}</div>' for e in c.evidence)
                st.markdown(
                    f'<div class="fl-cause"><div class="t">{html.escape(c.cause)}</div>'
                    f'<div style="margin-top:4px"><span class="l">{c.likelihood} likelihood</span>&nbsp;&nbsp;{cites(c.citations)}</div>'
                    f'{ev}</div>',
                    unsafe_allow_html=True)
    with right:
        with st.container(border=True):
            st.markdown('<div class="fl-sec">Recommended actions</div>', unsafe_allow_html=True)
            if not report.recommended_actions:
                st.markdown('<div class="fl-note">No actions reported.</div>', unsafe_allow_html=True)
            for i, act in enumerate(report.recommended_actions, 1):
                pc = PRIO.get(act.priority, INK3)
                st.markdown(
                    f'<div class="fl-act"><span class="n">{i:02d}</span><div><div class="s">{html.escape(act.step)}'
                    f'<span class="fl-prio"><span class="d" style="background:{pc}"></span>{PRIO_LABEL.get(act.priority, act.priority)}</span>'
                    f'</div><div style="margin-top:5px">{cites(act.citations)}</div></div></div>',
                    unsafe_allow_html=True)

    if report.uncertainties:
        st.markdown('<div style="height:12px"></div><div class="fl-sec">Uncertain about</div>', unsafe_allow_html=True)
        for u in report.uncertainties:
            st.markdown(f'<div class="fl-note">· {html.escape(str(u))}</div>', unsafe_allow_html=True)

    with st.expander(f"Evidence used ({len(evidence)})"):
        for e in evidence:
            st.markdown(f"**{e['id']}** · {e['title']}")
            st.caption(e["text"])
    with st.expander("Checks and guardrails"):
        st.json({"verifier": report.verification, "guardrails": report.guardrail_notes, "llm": meta})

    # ---------- human approval ----------
    if report.work_order:
        wo = report.work_order
        st.markdown('<div style="height:20px"></div><div class="fl-sec">Draft work order · needs approval</div>',
                    unsafe_allow_html=True)
        if st.session_state.get("discarded_order") is not None:
            c1, c2 = st.columns([5, 1])
            c1.info("Draft discarded. Nothing was raised.")
            if c2.button("Undo", help="Recover the discarded draft work order"):
                st.session_state.discarded_order = None
                st.rerun()
        else:
            with st.container(border=True):
                meta_cols = st.columns(3)
                meta_cols[0].markdown(f'<div class="fl-eyebrow">Asset</div><div style="color:var(--ink);font-weight:600">{html.escape(wo.asset)}</div>', unsafe_allow_html=True)
                meta_cols[1].markdown(f'<div class="fl-eyebrow">Downtime</div><div style="color:var(--ink);font-weight:600">' +
                                      (f"{wo.estimated_downtime_hours:g} h" if wo.estimated_downtime_hours else "Not estimated") + '</div>', unsafe_allow_html=True)
                meta_cols[2].markdown(f'<div class="fl-eyebrow">Parts or tools</div><div style="color:var(--ink-2)">' +
                                      (html.escape(", ".join(wo.parts_or_tools)) if wo.parts_or_tools else "None listed") + '</div>', unsafe_allow_html=True)
                st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
                title = st.text_input("Title", wo.title)
                prio = st.selectbox("Priority", ["P1", "P2", "P3"], index=["P1", "P2", "P3"].index(wo.priority))
                desc = st.text_area("Description", wo.description, height=130)
                approver = st.text_input("Approved by", placeholder="Name or badge number")

                st.session_state.approved_orders = st.session_state.get("approved_orders", set())
                is_approved = (wo.asset, cycle) in st.session_state.approved_orders
                if is_approved:
                    st.info(f"Work order for {wo.asset} at cycle {cycle} has already been approved in this session.")

                a1, a2 = st.columns([1, 1])
                if a1.button("Approve and raise work order", type="primary", disabled=(not approver or is_approved)):
                    if (wo.asset, cycle) not in st.session_state.approved_orders:
                        config.WORKORDERS_PATH.parent.mkdir(parents=True, exist_ok=True)
                        idempotency_key = f"{wo.asset}-{cycle}-{int(time.time())}"
                        record = {
                            "idempotency_key": idempotency_key,
                            "asset": wo.asset,
                            "title": title,
                            "priority": prio,
                            "description": desc,
                            "approved_by": approver,
                            "at": datetime.now(timezone.utc).isoformat(),
                        }
                        with open(config.WORKORDERS_PATH, "a", encoding="utf-8") as f:
                            if fcntl:
                                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                            try:
                                f.write(json.dumps(record) + "\n")
                            finally:
                                if fcntl:
                                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                        st.session_state.approved_orders.add((wo.asset, cycle))
                        st.success(f"Work order raised for {wo.asset}.")
                if a2.button("Reject"):
                    st.session_state.discarded_order = wo
                    st.rerun()
