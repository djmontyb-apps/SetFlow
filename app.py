
import io
import pandas as pd
import streamlit as st
from optimizer import Settings, optimize

st.set_page_config(page_title="SetFlow", page_icon="🎚️", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 1.6rem; padding-bottom: 2rem;}
h1 {letter-spacing: -0.04em;}
[data-testid="stMetricValue"] {font-size: 1.6rem;}
</style>
""", unsafe_allow_html=True)

st.title("🎚️ SetFlow")
st.caption("DJ playlist ordering by Camelot key, BPM, energy flow, and artist spacing.")

uploaded = st.file_uploader("Upload a playlist", type=["xlsx", "xls", "csv"])

with st.sidebar:
    st.header("Harmonize settings")
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

    key_pct = st.slider("Key priority", 0, 100, int(kw*100), 5)
    bpm_pct = 100 - key_pct
    st.caption(f"Key {key_pct}%  •  BPM {bpm_pct}%")

    bpm_tolerance = st.slider("BPM tolerance", 1, 12, 4, 1)
    half_double = st.checkbox("Allow half / double tempo matches", value=True)

    energy_mode = st.selectbox("Energy flow", ["Smooth", "Build"], index=0)
    energy_influence = st.slider("Energy influence", 0, 40, 15, 5) / 100.0

    artist_rule = st.select_slider(
        "Artist spacing",
        options=["Off", "Light", "Normal", "Strong"],
        value="Normal"
    )
    artist_penalty = {"Off":0.0, "Light":0.04, "Normal":0.08, "Strong":0.14}[artist_rule]

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
    st.dataframe(df, use_container_width=True, hide_index=True)

    invalid_keys = ~df["Camelot Key"].astype(str).str.upper().str.match(r"^(1[0-2]|[1-9])[AB]$")
    if invalid_keys.any():
        st.warning(f"{int(invalid_keys.sum())} track(s) have missing or invalid Camelot keys. They can still be optimized, but key scoring will be neutral.")

    if st.button("⚡ Optimize playlist", type="primary", use_container_width=True):
        records = df.to_dict(orient="records")
        settings = Settings(
            key_weight=key_pct/100.0,
            bpm_weight=bpm_pct/100.0,
            bpm_tolerance=float(bpm_tolerance),
            allow_half_double=half_double,
            energy_influence=energy_influence,
            artist_spacing=artist_penalty,
            energy_mode=energy_mode,
            depth=depth,
            lock_first=lock_first,
            lock_last=lock_last,
        )

        ordered, transitions = optimize(records, settings)
        out = pd.DataFrame(ordered).copy()
        out.insert(0, "SetFlow #", range(1, len(out)+1))

        # Transition information belongs to the destination track.
        scores = [None] + [t["score"] for t in transitions]
        key_scores = [None] + [t["key_score"] for t in transitions]
        bpm_scores = [None] + [t["bpm_score"] for t in transitions]
        bpm_diffs = [None] + [t["bpm_diff"] for t in transitions]
        out["Transition Score"] = scores
        out["Key Score"] = key_scores
        out["BPM Score"] = bpm_scores
        out["Effective BPM Δ"] = bpm_diffs

        avg_score = sum(t["score"] for t in transitions) / max(len(transitions), 1)
        weak = sum(1 for t in transitions if t["score"] < 60)
        great = sum(1 for t in transitions if t["score"] >= 85)

        st.success("Optimization complete.")
        c1, c2, c3 = st.columns(3)
        c1.metric("Average transition", f"{avg_score:.1f}/100")
        c2.metric("Great transitions", great)
        c3.metric("Weak transitions", weak)

        st.subheader("Optimized running order")
        show_cols = ["SetFlow #", "Title", "Artist", "BPM", "Camelot Key", "Energy",
                     "Transition Score", "Effective BPM Δ"]
        st.dataframe(out[show_cols], use_container_width=True, hide_index=True)

        with st.expander("Transition details"):
            detail_rows = []
            for i, t in enumerate(transitions):
                detail_rows.append({
                    "From": ordered[i]["Title"],
                    "To": ordered[i+1]["Title"],
                    "Score": t["score"],
                    "Key": t["key_score"],
                    "BPM": t["bpm_score"],
                    "Energy": t["energy_score"],
                    "BPM Δ": t["bpm_diff"],
                    "Same artist": t["same_artist"],
                })
            st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)

        csv_bytes = out.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download optimized CSV",
            csv_bytes,
            file_name="SetFlow_optimized_playlist.csv",
            mime="text/csv",
            use_container_width=True
        )

        xbuf = io.BytesIO()
        with pd.ExcelWriter(xbuf, engine="openpyxl") as writer:
            out.to_excel(writer, index=False, sheet_name="SetFlow Order")
        st.download_button(
            "Download optimized Excel",
            xbuf.getvalue(),
            file_name="SetFlow_optimized_playlist.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
else:
    st.info("Upload the Salsa spreadsheet we built, or any CSV/XLSX with Title, Artist, BPM, Camelot Key, and Energy.")
    st.markdown("""
**SetFlow v0.1 workflow**

1. Build or transfer your playlist.
2. Add Camelot keys from djay Pro / Mixed In Key.
3. Upload the spreadsheet.
4. Choose BPM vs Key priority and tolerance.
5. Optimize.
6. Export the running order.
""")
