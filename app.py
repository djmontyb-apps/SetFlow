import io
import pandas as pd
import streamlit as st
from optimizer import (
    Settings,
    optimize,
    energy_arc_details,
    energy_zone_labels,
    artist_spacing_stats,
    vibe_program_details,
)

st.set_page_config(page_title="SetFlow 1.1", page_icon="🎚️", layout="wide")

st.markdown(
    """
<style>
.block-container {padding-top: 1.8rem; padding-bottom: 3rem; max-width: 1420px;}
h1 {letter-spacing: -0.045em; margin-bottom: .15rem;}
h2, h3 {letter-spacing: -0.02em;}
[data-testid="stMetricValue"] {font-size: 1.55rem;}
[data-testid="stSidebar"] {border-right: 1px solid rgba(128,128,128,.15);}
.sf-eyebrow {font-size:.82rem; font-weight:700; text-transform:uppercase; letter-spacing:.08em; opacity:.65;}
.sf-hero {padding:.1rem 0 .45rem 0;}
.sf-tagline {font-size:1.08rem; opacity:.76; margin-top:.1rem; max-width:760px;}
.sf-card {border:1px solid rgba(128,128,128,.22); border-radius:16px; padding:1rem 1.05rem; min-height:126px; background:rgba(128,128,128,.035);}
.sf-card b {font-size:1rem;}
.sf-card p {margin:.42rem 0 0 0; opacity:.76; line-height:1.45;}
.sf-health {border:1px solid rgba(128,128,128,.22); border-radius:16px; padding:1rem 1.1rem; margin:.2rem 0 1rem 0;}
.sf-health-title {font-size:1.05rem; font-weight:750;}
.sf-muted {opacity:.70;}
div[data-testid="stFileUploader"] section {border-radius:14px;}
div[data-testid="stButton"] button[kind="primary"] {font-weight:700; min-height:3rem;}
</style>
""",
    unsafe_allow_html=True,
)


def normalize_columns(df):
    """Accept common playlist-export header variants without changing the optimizer schema."""
    aliases = {
        "title": "Title",
        "artist": "Artist",
        "bpm": "BPM",
        "camelot key": "Camelot Key",
        "camelot": "Camelot Key",
        "energy": "Energy",
        "dance": "Danceability",
        "danceability": "Danceability",
        "valence": "Valence",
        "pop.": "Popularity",
        "pop": "Popularity",
        "popularity": "Popularity",
    }
    df = df.copy()
    df.columns = [aliases.get(str(c).strip().lower(), str(c).strip()) for c in df.columns]
    return df


def load_playlist(file):
    name = file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)
    return normalize_columns(df)


def set_health(avg_score, weak, hard_bpm, max_bpm_diff, adjacent_artist, programming):
    if hard_bpm > 0:
        return "Needs Review", "A hard BPM jump remains. Check transition details before performing."
    if weak == 0 and adjacent_artist == 0 and avg_score >= 82 and programming >= 75:
        return "Excellent", "Tempo-safe, clean artist spacing, and no weak transitions."
    if weak <= 2 and adjacent_artist == 0 and avg_score >= 78:
        return "Strong", "Performance-ready route with only a couple of transitions worth previewing."
    if weak <= 4 and avg_score >= 74:
        return "Good", "Solid route. Preview the weak links and make any taste-based edits you want."
    return "Review", "The route is usable, but several transitions deserve a manual listen."


with st.sidebar:
    st.markdown("### 🎚️ SetFlow 1.1")
    st.caption("Whole-set DJ sequencing")

    mode = st.segmented_control("Preset", ["Smooth", "Balanced", "Harmonic"], default="Balanced")
    defaults = {
        "Smooth": (0.45, 0.55),
        "Balanced": (0.60, 0.40),
        "Harmonic": (0.75, 0.25),
    }
    kw, bw = defaults.get(mode, (0.60, 0.40))

    st.markdown("#### Mixing Brain")
    key_pct = st.slider(
        "Key preference",
        0,
        100,
        int(kw * 100),
        5,
        help="Inside a safe BPM neighborhood, how much should Camelot harmony matter?",
    )
    bpm_pct = 100 - key_pct
    st.caption(f"Inside a safe tempo zone: Key {key_pct}% • BPM {bpm_pct}%")

    bpm_tolerance = st.slider("Ideal BPM tolerance", 1, 12, 4, 1)
    bpm_guardrail = st.slider(
        "BPM guardrail",
        5,
        16,
        8,
        1,
        help="Beyond this difference, a great Camelot match cannot rescue the transition.",
    )

    with st.expander("Mixing safety", expanded=False):
        half_double = st.checkbox("Allow half / double tempo matches", value=True)
        escape_mode = st.checkbox(
            "BPM Escape Mode",
            value=True,
            help="When key harmony is awkward, prefer practical tempo placement.",
        )
        bpm_spine = st.checkbox(
            "BPM Bridge Planner",
            value=True,
            help="Protects bridge tracks so tempo islands do not create a cliff later in the set.",
        )
        min_target = st.slider("Minimum transition target", 40, 80, 60, 5)

    st.markdown("#### Programming Brain")
    energy_arc = st.selectbox(
        "Energy program",
        ["Party Zones", "Build Zones", "Smooth", "Off"],
        index=0,
        help="Party Zones = Warm-up → Groove → Build → Peak → Finish.",
    )
    energy_arc_influence = st.slider(
        "Energy Zone influence",
        0,
        50,
        25,
        5,
        help="Soft whole-set programming preference. BPM safety still wins.",
    ) / 100.0

    artist_rule = st.select_slider(
        "Artist spacing", options=["Off", "Light", "Normal", "Strong"], value="Normal"
    )
    artist_penalty = {"Off": 0.0, "Light": 0.04, "Normal": 0.08, "Strong": 0.14}[artist_rule]

    with st.expander("Fine-tune the set", expanded=False):
        energy_mode = st.selectbox("Adjacent energy", ["Smooth", "Build"], index=0)
        energy_influence = st.slider("Adjacent Energy influence", 0, 40, 10, 5) / 100.0

        st.markdown("**Vibe tie-breaker**")
        vibe_mode = st.segmented_control(
            "Danceability + Valence", ["Off", "Light", "Normal"], default="Light"
        )
        vibe_defaults = {"Off": (0, 0), "Light": (5, 5), "Normal": (10, 8)}
        dv, vv = vibe_defaults.get(vibe_mode, (5, 5))
        danceability_influence = st.slider(
            "Danceability influence", 0, 15, dv, 1,
            help="Tie-breaker only. It cannot override BPM safety or Energy Zones."
        ) / 100.0
        valence_influence = st.slider(
            "Valence influence", 0, 15, vv, 1,
            help="Tie-breaker only. Helps reduce abrupt mood whiplash."
        ) / 100.0

        depth = st.selectbox("Optimization depth", ["Quick", "Standard", "Deep"], index=1)
        lock_first = st.checkbox("Lock first track", value=False)
        lock_last = st.checkbox("Lock last track", value=False)

st.markdown('<div class="sf-hero">', unsafe_allow_html=True)
st.markdown('<div class="sf-eyebrow">DJ playlist optimizer</div>', unsafe_allow_html=True)
st.title("🎚️ SetFlow")
st.markdown(
    '<div class="sf-tagline">Make it mixable first. Make it harmonic second. Make the whole set flow.</div>',
    unsafe_allow_html=True,
)
st.markdown('</div>', unsafe_allow_html=True)

uploaded = st.file_uploader("Upload a playlist", type=["xlsx", "xls", "csv"])
st.caption("Required: Title, Artist, BPM, Camelot Key, Energy  •  Optional: Danceability, Valence, Popularity")

required = ["Title", "Artist", "BPM", "Camelot Key", "Energy"]

if not uploaded:
    st.write("")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            '<div class="sf-card"><b>🎛️ Mixing Brain</b><p>Builds a tempo-safe route first, then uses Camelot harmony inside practical BPM neighborhoods.</p></div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            '<div class="sf-card"><b>📈 Programming Brain</b><p>Shapes broad Energy Zones and spaces artists so the playlist feels like a set, not a spreadsheet.</p></div>',
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            '<div class="sf-card"><b>✨ Vibe Polish</b><p>Danceability and Valence break close ties without steering BPM, Camelot, or the energy plan.</p></div>',
            unsafe_allow_html=True,
        )
    st.caption("Tip: the Balanced preset + Party Zones is the recommended starting point.")
    st.stop()

try:
    df = load_playlist(uploaded)
except Exception as e:
    st.error(f"Could not read that file: {e}")
    st.stop()

missing = [c for c in required if c not in df.columns]
if missing:
    st.error("Missing required columns: " + ", ".join(missing))
    st.info("SetFlow needs: Title, Artist, BPM, Camelot Key, Energy.")
    st.stop()

st.subheader("Playlist ready")
meta1, meta2, meta3 = st.columns(3)
meta1.metric("Tracks", len(df))

invalid_keys = ~df["Camelot Key"].astype(str).str.upper().str.match(r"^(1[0-2]|[1-9])[AB]$")
meta2.metric("Valid Camelot keys", f"{len(df) - int(invalid_keys.sum())}/{len(df)}")

energy_num = pd.to_numeric(df["Energy"], errors="coerce")
suspicious_energy = energy_num.isna() | (energy_num <= 0) | (energy_num > 100)
meta3.metric("Usable Energy", f"{len(df) - int(suspicious_energy.sum())}/{len(df)}")

optional = [c for c in ["Danceability", "Valence", "Popularity"] if c in df.columns]
if optional:
    st.caption("Optional metadata detected: " + " • ".join(optional))
if invalid_keys.any():
    st.warning(f"{int(invalid_keys.sum())} track(s) have missing or invalid Camelot keys. Key scoring will stay neutral for those tracks.")
if suspicious_energy.any():
    st.info(f"{int(suspicious_energy.sum())} track(s) have missing/suspicious Energy values. SetFlow treats those as neutral, not literal zero.")
if vibe_mode != "Off":
    missing_optional = [c for c in ["Danceability", "Valence"] if c not in df.columns]
    if missing_optional:
        st.caption("Vibe tie-breaker: " + ", ".join(missing_optional) + " missing — neutral scoring will be used.")

with st.expander("Preview uploaded playlist", expanded=False):
    st.dataframe(df, width="stretch", hide_index=True)

if st.button("⚡ Build my SetFlow", type="primary", width="stretch"):
    records = df.to_dict(orient="records")
    settings = Settings(
        key_weight=key_pct / 100.0,
        bpm_weight=bpm_pct / 100.0,
        bpm_tolerance=float(bpm_tolerance),
        bpm_guardrail=float(bpm_guardrail),
        allow_half_double=half_double,
        escape_mode=escape_mode,
        bpm_spine=bpm_spine,
        min_transition_target=float(min_target),
        energy_influence=energy_influence,
        energy_mode=energy_mode,
        energy_arc=energy_arc,
        energy_arc_influence=energy_arc_influence,
        artist_spacing=artist_penalty,
        danceability_influence=danceability_influence,
        valence_influence=valence_influence,
        depth=depth,
        lock_first=lock_first,
        lock_last=lock_last,
    )

    with st.spinner("SetFlow is planning the whole set…"):
        ordered, transitions = optimize(records, settings)

    out = pd.DataFrame(ordered).copy()
    out.insert(0, "SetFlow #", range(1, len(out) + 1))
    out["Transition Score"] = [None] + [t["score"] for t in transitions]
    out["Transition Reason"] = ["OPEN"] + [t["reason"] for t in transitions]
    out["Transition Quality"] = ["OPEN"] + [t["quality"] for t in transitions]
    out["Camelot Move"] = [None] + [t["camelot_relationship"] for t in transitions]
    out["Effective BPM Δ"] = [None] + [t["bpm_diff"] for t in transitions]
    out["Program Zone"] = energy_zone_labels(ordered, settings)

    avg_score = sum(t["score"] for t in transitions) / max(len(transitions), 1)
    weak = sum(1 for t in transitions if t["score"] < min_target)
    great = sum(1 for t in transitions if t["score"] >= 85)
    bad_bpm = sum(1 for t in transitions if t["bpm_zone"] in ("Hard BPM Jump", "BPM Incompatible"))
    bpm_diffs = [t["bpm_diff"] for t in transitions if t["bpm_diff"] is not None]
    max_bpm_diff = max(bpm_diffs) if bpm_diffs else 0.0
    arc = energy_arc_details(ordered, settings)
    vibe = vibe_program_details(ordered, settings)
    adjacent_artist, near_artist = artist_spacing_stats(ordered)
    health, health_note = set_health(avg_score, weak, bad_bpm, max_bpm_diff, adjacent_artist, arc["score"])

    st.success("SetFlow complete.")
    st.markdown(
        f'<div class="sf-health"><div class="sf-health-title">Set Health: {health}</div><div class="sf-muted">{health_note}</div></div>',
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Avg transition", f"{avg_score:.1f}")
    c2.metric("Weak links", weak)
    c3.metric("Hard BPM jumps", bad_bpm)
    c4.metric("Worst BPM Δ", f"{max_bpm_diff:.1f}")
    c5.metric("Programming", f"{arc['score']:.1f}")
    c6.metric("Artist collisions", adjacent_artist)

    qualities = pd.Series([t["quality"] for t in transitions]).value_counts().to_dict()
    st.caption(
        "Route quality: "
        + " • ".join(
            [
                f"Excellent {qualities.get('Excellent', 0)}",
                f"Good {qualities.get('Good', 0)}",
                f"DJ Workable {qualities.get('DJ Workable', 0)}",
                f"BPM Escape {qualities.get('BPM Escape', 0)}",
                f"Weak {qualities.get('Weak', 0)}",
            ]
        )
    )
    if energy_arc != "Off":
        st.caption(
            f"Energy: start {arc['start']} • peak {arc['peak']} at track {arc.get('peak_position', '—')} • "
            f"finish {arc['finish']} • Vibe {vibe['score']:.1f} • near artist repeats {near_artist}"
        )

    if bad_bpm:
        st.warning("A hard BPM transition remains. Review that link before performing the set.")
    elif weak == 0:
        st.info("No transitions fell below your minimum target.")

    st.subheader("Optimized running order")
    show_cols = ["SetFlow #", "Title", "Artist", "BPM", "Camelot Key", "Energy"]
    for col in ["Danceability", "Valence"]:
        if col in out.columns:
            show_cols.append(col)
    show_cols += ["Program Zone", "Transition Score", "Transition Quality", "Transition Reason", "Effective BPM Δ"]
    st.dataframe(out[show_cols], width="stretch", hide_index=True)

    with st.expander("Transition details"):
        detail_rows = []
        for i, t in enumerate(transitions):
            detail_rows.append(
                {
                    "From": ordered[i]["Title"],
                    "To": ordered[i + 1]["Title"],
                    "Score": t["score"],
                    "Quality": t["quality"],
                    "Reason": t["reason"],
                    "Camelot move": t["camelot_relationship"],
                    "BPM zone": t["bpm_zone"],
                    "Tempo mode": t["tempo_mode"],
                    "Effective BPM Δ": t["bpm_diff"],
                    "Key score": t["key_score"],
                    "BPM score": t["bpm_score"],
                    "Energy score": t["energy_score"],
                    "Same artist": t["same_artist"],
                }
            )
        st.dataframe(pd.DataFrame(detail_rows), width="stretch", hide_index=True)

    d1, d2 = st.columns(2)
    csv_bytes = out.to_csv(index=False).encode("utf-8")
    d1.download_button(
        "Download CSV",
        csv_bytes,
        file_name="SetFlow_v1.1_optimized_playlist.csv",
        mime="text/csv",
        width="stretch",
    )

    xbuf = io.BytesIO()
    with pd.ExcelWriter(xbuf, engine="openpyxl") as writer:
        out.to_excel(writer, index=False, sheet_name="SetFlow Order")
    d2.download_button(
        "Download Excel",
        xbuf.getvalue(),
        file_name="SetFlow_v1.1_optimized_playlist.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )
