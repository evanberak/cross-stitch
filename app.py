"""
Photo-to-Cross-Stitch Converter — Streamlit front end.

Design intent: the default path is upload -> convert -> download PDF.
Everything else lives behind "Advanced options" so a first-time user is never
asked a question they don't yet have an opinion about.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st
from PIL import Image

import renderers as R
from pdf_export import build_pdf
from stitch_engine import convert, load_palette, prepare_image, replace_color

st.set_page_config(page_title="Photo to Cross Stitch", page_icon="🧵",
                   layout="centered")

st.markdown("""
<style>
  .block-container {padding-top: 2.4rem; max-width: 900px;}
  h1 {letter-spacing:-.025em; margin-bottom:.1rem;}
  .tagline {color:#6b7280; font-size:1.05rem; margin-top:-.2rem;
            margin-bottom:1.4rem;}
  .stat {background:#faf9f6; border:1px solid #e9e7e1; border-radius:10px;
         padding:.6rem .8rem; text-align:center;}
  .stat b {display:block; font-size:1.15rem; color:#111827; line-height:1.3;}
  .stat span {font-size:.66rem; text-transform:uppercase; letter-spacing:.07em;
              color:#9a9a92;}
  div[data-testid="stExpander"] details {border-radius:10px;}
</style>
""", unsafe_allow_html=True)

st.title("Photo to Cross Stitch")
st.markdown('<p class="tagline">Turn your favorite photo into a cross-stitch '
            'pattern in minutes.</p>', unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Cached resources
# --------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_palette():
    return load_palette()


@st.cache_data(show_spinner=False)
def load_upload(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


@st.cache_data(show_spinner="Converting your photo…")
def run_conversion(img_bytes: bytes, sw: int, sh: int, ncolors: int,
                   count: float, smoothing: float, locked: tuple[str, ...],
                   adj: tuple, crop: tuple):
    """Cached so UI-only changes (chart style, title) don't re-run the pipeline."""
    base = load_upload(img_bytes)
    prepped = prepare_image(base, *adj, crop_box=crop)
    return convert(prepped, sw, sh, ncolors, count, get_palette(),
                   smoothing=smoothing, locked_numbers=list(locked))


palette = get_palette()

# --------------------------------------------------------------------------
# Step 1 — upload
# --------------------------------------------------------------------------

upload = st.file_uploader("Upload a photo",
                          type=["png", "jpg", "jpeg", "webp", "bmp"],
                          label_visibility="collapsed")

if not upload:
    st.info("**Upload a photo to begin.** Portraits, pets and high-contrast "
            "subjects convert best. You'll get a preview and a printable "
            "pattern PDF.")
    st.stop()

# --------------------------------------------------------------------------
# Step 2 — the three choices that actually matter
# --------------------------------------------------------------------------

c1, c2, c3 = st.columns(3)

with c1:
    size_label = st.select_slider(
        "Pattern size",
        options=["Small", "Medium", "Large", "Extra large"],
        value="Medium",
        help="Roughly how wide the finished piece will be.",
    )
with c2:
    detail_label = st.select_slider(
        "Detail",
        options=["Simple", "Balanced", "Detailed"],
        value="Balanced",
        help="More detail means more colors and finer shading — and more work.",
    )
with c3:
    count_choice = st.selectbox(
        "Fabric count", ["11 count", "14 count", "16 count", "18 count"],
        index=1,
        help="Stitches per inch. 14 is the most common for beginners.",
    )

# Map the friendly labels onto real parameters.
SIZE_INCHES = {"Small": 6.0, "Medium": 10.0, "Large": 14.0, "Extra large": 18.0}
DETAIL = {"Simple": (12, 0.35), "Balanced": (22, 0.55), "Detailed": (36, 0.78)}

fabric_count = float(count_choice.split()[0])
target_inches = SIZE_INCHES[size_label]
auto_colors, complexity = DETAIL[detail_label]

# --------------------------------------------------------------------------
# Advanced options — everything else lives here
# --------------------------------------------------------------------------

with st.expander("Advanced options"):
    a_tabs = st.tabs(["Size & color", "Image", "Crop", "Threads", "Output"])

    with a_tabs[0]:
        override_size = st.checkbox("Set exact stitch dimensions")
        if override_size:
            sc1, sc2 = st.columns(2)
            stitch_w_override = sc1.number_input("Stitch width", 20, 500,
                                                 int(target_inches * fabric_count), 5)
            custom_count = sc2.number_input("Custom fabric count (0 = use above)",
                                            0.0, 40.0, 0.0, 1.0)
            if custom_count > 0:
                fabric_count = custom_count
        else:
            stitch_w_override = None

        override_colors = st.checkbox("Set exact color count")
        if override_colors:
            max_colors = st.slider("Maximum thread colors", 4, 60, auto_colors, 1)
        else:
            max_colors = auto_colors
            st.caption(f"Using {auto_colors} colors from the "
                       f"'{detail_label}' preset.")

        smoothing = round((1.0 - complexity) * 1.6, 2)
        smoothing = st.slider(
            "Smoothing", 0.0, 2.0, smoothing, 0.05,
            help="Higher values reduce speckle in noisy photos and busy "
                 "backgrounds, at the cost of fine detail.")

    with a_tabs[1]:
        i1, i2 = st.columns(2)
        brightness = i1.slider("Brightness", 0.4, 1.8, 1.0, 0.05)
        contrast = i2.slider("Contrast", 0.4, 2.0, 1.05, 0.05)
        saturation = i1.slider("Saturation", 0.0, 2.0, 1.1, 0.05)
        sharpen = i2.slider("Sharpen", 0.0, 3.0, 1.2, 0.1)

    with a_tabs[2]:
        cl, cr = st.slider("Horizontal", 0.0, 1.0, (0.0, 1.0), 0.01)
        ct, cb = st.slider("Vertical", 0.0, 1.0, (0.0, 1.0), 0.01)
        st.caption("Cropping tightly around your subject usually improves the "
                   "result more than any other setting.")

    with a_tabs[3]:
        st.caption("Locked threads are guaranteed to appear in the pattern. "
                   "Useful for skin tones, or floss you already own.")
        lock_opts = [f"{f.number} — {f.name}" for f in palette]
        locked_sel = st.multiselect("Lock specific threads", lock_opts, [])
        locked = tuple(s.split(" — ")[0] for s in locked_sel)

    with a_tabs[4]:
        o1, o2 = st.columns(2)
        pagesize = o1.selectbox("Page size", ["A4", "Letter"])
        strands = o2.selectbox("Strands used", [1, 2, 3, 4], index=1)
        chart_style = o1.selectbox("Chart style",
                                   ["Black & white symbols", "Symbols over color"])
        cells = o2.slider("Stitches per chart page", 30, 70, 50, 5)
        st.checkbox("Large-print charts", key="large_print")

# --------------------------------------------------------------------------
# Convert
# --------------------------------------------------------------------------

img_bytes = upload.getvalue()
original = prepare_image(load_upload(img_bytes), brightness, contrast,
                         saturation, sharpen, (cl, ct, cr, cb))

stitch_w = stitch_w_override or max(20, int(round(target_inches * fabric_count)))
stitch_h = max(20, int(round(stitch_w * original.height / original.width)))

if stitch_w * stitch_h > 220_000:
    st.warning("That grid is very large — slow to convert, and a serious "
               "commitment to stitch. Consider a smaller size.")

pattern = run_conversion(
    img_bytes, stitch_w, stitch_h, max_colors, fabric_count, smoothing,
    locked, (brightness, contrast, saturation, sharpen), (cl, ct, cr, cb),
)

for idx, num in st.session_state.get("swaps", {}).items():
    if idx < len(pattern.colors):
        match = next((f for f in palette if f.number == num), None)
        if match:
            pattern = replace_color(pattern, idx, match)

# --------------------------------------------------------------------------
# Preview + stats
# --------------------------------------------------------------------------

st.image(R.side_by_side(original, pattern), use_container_width=True)

fw_in, fh_in = pattern.finished_inches
fw_cm, fh_cm = pattern.finished_cm
stats = [
    ("Stitches", f"{pattern.stitch_w} × {pattern.stitch_h}"),
    ("Finished", f"{fw_in:.1f} × {fh_in:.1f} in"),
    ("Metric", f"{fw_cm:.0f} × {fh_cm:.0f} cm"),
    ("Colors", f"{len(pattern.colors)}"),
]
for col, (label, val) in zip(st.columns(4), stats):
    col.markdown(f'<div class="stat"><span>{label}</span><b>{val}</b></div>',
                 unsafe_allow_html=True)

st.write("")

# --------------------------------------------------------------------------
# Step 3 — download (the primary action)
# --------------------------------------------------------------------------

title = st.text_input("Pattern title", "My Cross Stitch Pattern")

if st.button("Build pattern PDF", type="primary", use_container_width=True):
    with st.spinner("Laying out pages…"):
        st.session_state["pdf"] = build_pdf(
            pattern, title=title, pagesize_name=pagesize, strands=strands,
            over_color=(chart_style == "Symbols over color"),
            cells_per_page=cells)

if st.session_state.get("pdf"):
    st.download_button("Download pattern PDF", st.session_state["pdf"],
                       f"{title.replace(' ', '_')}.pdf", "application/pdf",
                       type="primary", use_container_width=True)

# --------------------------------------------------------------------------
# Secondary: other views, full color key, PNGs
# --------------------------------------------------------------------------

with st.expander("More previews and the full color key"):
    lp = st.session_state.get("large_print", False)
    v = st.tabs(["Stitch simulation", "Color blocks", "Symbols",
                 "Symbols over color"])
    with v[0]:
        st.image(R.stitch_simulation(pattern, scale=10), use_container_width=True)
    with v[1]:
        st.image(R.flat_color(pattern, scale=8), use_container_width=True)
    with v[2]:
        st.image(R.symbol_chart(pattern, over_color=False, large_print=lp),
                 use_container_width=True)
    with v[3]:
        st.image(R.symbol_chart(pattern, over_color=True, large_print=lp),
                 use_container_width=True)

    st.markdown("**Color key**")
    df = pd.DataFrame(R.legend_swatches(pattern))
    st.dataframe(
        df, use_container_width=True, hide_index=True,
        column_config={
            "% of pattern": st.column_config.ProgressColumn(
                "% of pattern", min_value=0.0,
                max_value=float(df["% of pattern"].max()), format="%.1f%%"),
        },
    )
    st.caption("Skein figures are estimates only — technique, fabric and "
               "waste all change real usage.")

    st.markdown("**Replace a thread**")
    r1, r2, r3 = st.columns([2, 2, 1])
    which = r1.selectbox(
        "Pattern color", range(len(pattern.colors)),
        format_func=lambda i: (f"{pattern.colors[i].symbol}  "
                               f"{pattern.colors[i].floss.number} — "
                               f"{pattern.colors[i].floss.name}"))
    new = r2.selectbox("Replace with",
                       [f"{f.number} — {f.name}" for f in palette])
    r3.write("")
    if r3.button("Apply", use_container_width=True):
        st.session_state.setdefault("swaps", {})[which] = new.split(" — ")[0]
        st.rerun()
    if st.session_state.get("swaps") and st.button("Clear all swaps"):
        st.session_state["swaps"] = {}
        st.rerun()

    p1, p2 = st.columns(2)
    png = io.BytesIO()
    R.stitch_simulation(pattern, scale=12).save(png, format="PNG")
    p1.download_button("Preview PNG", png.getvalue(), "pattern_preview.png",
                       "image/png", use_container_width=True)
    chart = io.BytesIO()
    R.symbol_chart(pattern, over_color=(chart_style == "Symbols over color"),
                   large_print=lp).save(chart, format="PNG")
    p2.download_button("Chart PNG", chart.getvalue(), "pattern_chart.png",
                       "image/png", use_container_width=True)

st.divider()
st.caption(
    "Cross stitch requires deliberate simplification — a converted photo is an "
    "interpretation, not a reproduction. Adjust size, detail and cropping until "
    "the chart reads well at stitching scale."
)
