import io
import pandas as pd
import streamlit as st
from optimizer import Settings, optimize

st.set_page_config(page_title="SetFlow v0.4", page_icon="🎚️", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 1.6rem; padding-bottom: 2rem;}
h1 {letter-spacing: -0.04em;}
[data-testid="stMetricValue"] {font-size: 1.6rem;}
</style>
""", unsafe_allow_html=True)

st.title("🎚️ SetFlow")
st.caption("v0.4 • Mixable first. Harmonic second. Make the whole set flow.")

uploaded = st.file_uploader("Upload a playlist", type=["xlsx", "xls", "csv"])

with st.sidebar:
    st.header("SetFlow settings")
    mode = st.segmented_control(
        "Preset",
        ["Smooth", "Balanced", "Harmonic"],
        default="Balanced"
    )

    defaults = {
        "Smooth": (0.45, 0.55),
        "Balanced": (0.60, 0.40),
        "Harmonic": (0.75, 0.25),
    }
    kw, bw = defaults.get(mode, (0.60, 0.40))

    key_pct = st.slider("Key preference", 0, 100, int(kw * 100), 5,
                        help="BPM guardrails still apply even at high Key preference.")
    bpm_pct = 100 - key_pct
    st.caption(f"Inside a mixable BPM zone: Key {key_pct}% • BPM {bpm_pct}%")

    st.subheader("DJ Safety")
    bpm_tolerance = st.slider("Ideal BPM tolerance", 1, 12, 4, 1)
    bpm_guardrail = st.slider("BPM guardrail", 5, 16, 8, 1,
                              help="Beyond this, harmonic key cannot rescue a big tempo jump.")
    half_double = st.checkbox("Allow half / double tempo matches", value=True)
    escape_mode = st.checkbox("BPM Escape Mode", value=True,
                              help="When harmony is awkward, place the track where tempo makes practical DJ sense.")
    min_target = st.slider("Minimum transition target", 40, 80, 60, 5)

    st.subheader("Flow")
    energy_mode = st.selectbox("Energy flow", ["Smooth", "Build"], index=0)
    energy_influence = st.slider("Energy influence", 0, 40, 15, 5) / 100.0

    artist_rule = st.select_slider(
        "Artist spacing",
        options=["Off", "Light", "Normal", "Strong"],
        value="Normal"
    )
    artist_penalty = {"Off": 0.0, "Light": 0.04, "Normal": 0.08, "Strong": 0.14}[artist_rule]

    depth = st.selectbox("Optimization depth", ["Quick", "Standard", "Deep"], index=1)
    lock_first = st.checkbox("Lock first track", value=False)
    lock_last = st.checkbox("Lock last track", value=False)


def load_playlist(file):
    name = file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(file)
    return pd.read_excel(file)


required = ["Title", "Artist", "BPM", "Camelot Key", "Energy"]

if uploaded:
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

    st.subheader("Playlist")
    st.caption(f"{len(df)} tracks loaded")
    st.dataframe(df, width="stretch", hide_index=True)

    invalid_keys = ~df["Camelot Key"].astype(str).str.upper().str.match(r"^(1[0-2]|[1-9])[AB]$")
    if invalid_keys.any():
        st.warning(f"{int(invalid_keys.sum())} track(s) have missing or invalid Camelot keys. Key scoring will be neutral for those tracks.")

    energy_num = pd.to_numeric(df["Energy"], errors="coerce")
    suspicious_energy = energy_num.isna() | (energy_num <= 0) | (energy_num > 100)
    if suspicious_energy.any():
        st.info(f"{int(suspicious_energy.sum())} track(s) have missing/suspicious Energy values. SetFlow v0.4 treats those as neutral instead of literal zero.")

    if st.button("⚡ Optimize playlist", type="primary", width="stretch"):
        records = df.to_dict(orient="records")
        settings = Settings(
            key_weight=key_pct / 100.0,
            bpm_weight=bpm_pct / 100.0,
            bpm_tolerance=float(bpm_tolerance),
            bpm_guardrail=float(bpm_guardrail),
            allow_half_double=half_double,
            escape_mode=escape_mode,
            min_transition_target=float(min_target),
            energy_influence=energy_influence,
            artist_spacing=artist_penalty,
            energy_mode=energy_mode,
            depth=depth,
            lock_first=lock_first,
            lock_last=lock_last,
        )

        with st.spinner("SetFlow is building the best whole-set route…"):
            ordered, transitions = optimize(records, settings)

        out = pd.DataFrame(ordered).copy()
        out.insert(0, "SetFlow #", range(1, len(out) + 1))

        out["Transition Score"] = [None] + [t["score"] for t in transitions]
        out["Transition Reason"] = ["OPEN"] + [t["reason"] for t in transitions]
        out["Transition Quality"] = ["OPEN"] + [t["quality"] for t in transitions]
        out["Camelot Move"] = [None] + [t["camelot_relationship"] for t in transitions]
        out["Effective BPM Δ"] = [None] + [t["bpm_diff"] for t in transitions]

        avg_score = sum(t["score"] for t in transitions) / max(len(transitions), 1)
        weak = sum(1 for t in transitions if t["score"] < min_target)
        great = sum(1 for t in transitions if t["score"] >= 85)
        escapes = sum(1 for t in transitions if t["reason"] == "BPM Escape")
        bad_bpm = sum(1 for t in transitions if t["bpm_zone"] in ("Hard BPM Jump", "BPM Incompatible"))

        st.success("Optimization complete.")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Average transition", f"{avg_score:.1f}/100")
        c2.metric("Great transitions", great)
        c3.metric("Weak transitions", weak)
        c4.metric("BPM Escapes", escapes)

        if bad_bpm:
            st.warning(f"SetFlow found {bad_bpm} unavoidable hard BPM transition(s). Check the transition details before performing the set.")
        elif weak == 0:
            st.info("No transitions fell below your minimum target. Nice route.")

        st.subheader("Optimized running order")
        show_cols = [
            "SetFlow #", "Title", "Artist", "BPM", "Camelot Key", "Energy",
            "Transition Score", "Transition Quality", "Transition Reason", "Effective BPM Δ"
        ]
        st.dataframe(out[show_cols], width="stretch", hide_index=True)

        with st.expander("Transition details"):
            detail_rows = []
            for i, t in enumerate(transitions):
                detail_rows.append({
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
                })
            st.dataframe(pd.DataFrame(detail_rows), width="stretch", hide_index=True)

        csv_bytes = out.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download optimized CSV",
            csv_bytes,
            file_name="SetFlow_v0.4_optimized_playlist.csv",
            mime="text/csv",
            width="stretch"
        )

        xbuf = io.BytesIO()
        with pd.ExcelWriter(xbuf, engine="openpyxl") as writer:
            out.to_excel(writer, index=False, sheet_name="SetFlow Order")
        st.download_button(
            "Download optimized Excel",
            xbuf.getvalue(),
            file_name="SetFlow_v0.4_optimized_playlist.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch"
        )
else:
    st.info("Upload the Salsa spreadsheet we built, or any CSV/XLSX with Title, Artist, BPM, Camelot Key, and Energy.")
    st.markdown("""
**What changed in SetFlow v0.4**

- **Anti-garbage-pile rescue:** SetFlow targets the weakest transitions and tries moving those tracks earlier into better BPM neighborhoods.
- **Worst-link-first scoring:** one disastrous transition now hurts more than several small score improvements can help.
- BPM remains the practical guardrail; Camelot harmony is optimized inside a mixable tempo zone.
- BPM Escape Mode deliberately breaks key when that produces a more DJ-friendly tempo transition.
- Missing or zero Energy metadata is treated as neutral.
- Every transition explains *why* SetFlow chose it.
""")
