"""
Photo-to-Cross-Stitch Converter — Streamlit front end.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import io

import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image

import renderers as R
from pdf_export import build_pdf
from stitch_engine import (
    Floss,
    convert,
    load_palette,
    prepare_image,
    replace_color,
)

st.set_page_config(page_title="Photo to Cross Stitch", page_icon="🧵",
                   layout="wide")

st.markdown("""
<style>
  .block-container {padding-top: 2.2rem; max-width: 1300px;}
  h1 {letter-spacing:-.02em;}
  .tagline {color:#6b7280; font-size:1.02rem; margin-top:-.6rem;}
  .stat {background:#f8f7f4; border:1px solid #e7e5e0; border-radius:10px;
         padding:.7rem .9rem;}
  .stat b {display:block; font-size:1.25rem; color:#111827;}
  .stat span {font-size:.72rem; text-transform:uppercase; letter-spacing:.06em;
              color:#8b8b85;}
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


@st.cache_data(show_spinner="Converting…")
def run_conversion(img_bytes: bytes, sw: int, sh: int, ncolors: int,
                   count: float, smoothing: float, locked: tuple[str, ...],
                   adj: tuple, crop: tuple):
    """Cached so UI-only changes (chart style, page size) don't re-run it."""
    base = load_upload(img_bytes)
    prepped = prepare_image(base, *adj, crop_box=crop)
    return convert(prepped, sw, sh, ncolors, count, get_palette(),
                   smoothing=smoothing, locked_numbers=list(locked))


palette = get_palette()

# --------------------------------------------------------------------------
# Sidebar controls
# --------------------------------------------------------------------------

with st.sidebar:
    st.header("1. Photo")
    upload = st.file_uploader("Upload an image",
                              type=["png", "jpg", "jpeg", "webp", "bmp"])

    st.header("2. Fabric")
    count_choice = st.selectbox("Fabric count",
                                ["11 count", "14 count", "16 count",
                                 "18 count", "Custom"], index=1)
    if count_choice == "Custom":
        fabric_count = st.number_input("Stitches per inch", 6.0, 40.0, 14.0, 1.0)
    else:
        fabric_count = float(count_choice.split()[0])

    size_mode = st.radio("Set size by", ["Stitch width", "Finished width (in)"],
                         horizontal=True)
    if size_mode == "Stitch width":
        stitch_w = st.slider("Stitch width", 40, 400, 140, 5)
    else:
        finished_w = st.slider("Finished width (inches)", 2.0, 20.0, 10.0, 0.5)
        stitch_w = max(20, int(round(finished_w * fabric_count)))
        st.caption(f"≈ {stitch_w} stitches wide")

    st.header("3. Colors")
    preset = st.selectbox("Detail preset",
                          ["Custom", "Simple", "Balanced", "Detailed",
                           "Portrait / pet"], index=2)
    defaults = {"Simple": (10, 0.35), "Balanced": (20, 0.55),
                "Detailed": (34, 0.75), "Portrait / pet": (26, 0.45)}
    if preset in defaults:
        d_colors, d_complex = defaults[preset]
    else:
        d_colors, d_complex = 20, 0.5

    max_colors = st.slider("Maximum thread colors", 4, 60, d_colors, 1)
    complexity = st.slider("Simple  ←→  Detailed", 0.0, 1.0, d_complex, 0.05,
                           help="Influences smoothing and edge retention.")
    smoothing = round((1.0 - complexity) * 1.6, 2)

    st.header("4. Adjustments")
    brightness = st.slider("Brightness", 0.4, 1.8, 1.0, 0.05)
    contrast = st.slider("Contrast", 0.4, 2.0, 1.05, 0.05)
    saturation = st.slider("Saturation", 0.0, 2.0, 1.1, 0.05)
    sharpen = st.slider("Sharpen", 0.0, 3.0, 1.2, 0.1)

    with st.expander("Crop"):
        cl, cr = st.slider("Horizontal", 0.0, 1.0, (0.0, 1.0), 0.01)
        ct, cb = st.slider("Vertical", 0.0, 1.0, (0.0, 1.0), 0.01)

    with st.expander("Lock threads"):
        st.caption("Locked colors are favoured when matching. Useful for skin "
                   "tones or a background you have already bought floss for.")
        lock_opts = [f"{f.number} — {f.name}" for f in palette]
        locked_sel = st.multiselect("Threads to favour", lock_opts, [])
        locked = tuple(s.split(" — ")[0] for s in locked_sel)

if not upload:
    st.info("Upload a photo in the sidebar to begin. Portraits, pets and "
            "high-contrast subjects convert best.")
    st.stop()

# --------------------------------------------------------------------------
# Convert
# --------------------------------------------------------------------------

img_bytes = upload.getvalue()
original = prepare_image(load_upload(img_bytes), brightness, contrast,
                         saturation, sharpen, (cl, ct, cr, cb))
ar = original.height / original.width
stitch_h = max(20, int(round(stitch_w * ar)))

if stitch_w * stitch_h > 220_000:
    st.warning("That grid is very large and will be slow to convert and "
               "stitch. Consider reducing the width.")

pattern = run_conversion(
    img_bytes, stitch_w, stitch_h, max_colors, fabric_count, smoothing,
    locked, (brightness, contrast, saturation, sharpen), (cl, ct, cr, cb),
)

# Apply any manual replacements stored in session state.
for idx, num in st.session_state.get("swaps", {}).items():
    if idx < len(pattern.colors):
        match = next((f for f in palette if f.number == num), None)
        if match:
            pattern = replace_color(pattern, idx, match)

# --------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------

fw_in, fh_in = pattern.finished_inches
fw_cm, fh_cm = pattern.finished_cm

cols = st.columns(5)
stats = [
    ("Stitch count", f"{pattern.stitch_w} × {pattern.stitch_h}"),
    ("Total stitches", f"{pattern.total_stitches:,}"),
    ("Finished (in)", f"{fw_in:.1f} × {fh_in:.1f}"),
    ("Finished (cm)", f"{fw_cm:.1f} × {fh_cm:.1f}"),
    ("Thread colors", f"{len(pattern.colors)}"),
]
for col, (label, val) in zip(cols, stats):
    col.markdown(f'<div class="stat"><span>{label}</span><b>{val}</b></div>',
                 unsafe_allow_html=True)

st.write("")

# --------------------------------------------------------------------------
# Previews
# --------------------------------------------------------------------------

tabs = st.tabs(["Before / after", "Stitch simulation", "Color blocks",
                "Symbols only", "Symbols over color"])

with tabs[0]:
    st.image(R.side_by_side(original, pattern), use_container_width=True)
    st.caption("Left: your photo. Right: how it converts. Adjust the sliders "
               "and watch both sides.")

with tabs[1]:
    st.image(R.stitch_simulation(pattern, scale=10), use_container_width=True)

with tabs[2]:
    st.image(R.flat_color(pattern, scale=8), use_container_width=True)

large_print = st.session_state.get("large_print", False)
with tabs[3]:
    st.image(R.symbol_chart(pattern, over_color=False, large_print=large_print),
             use_container_width=True)

with tabs[4]:
    st.image(R.symbol_chart(pattern, over_color=True, large_print=large_print),
             use_container_width=True)

# --------------------------------------------------------------------------
# Legend + manual replacement
# --------------------------------------------------------------------------

st.subheader("Color key")
left, right = st.columns([3, 2])

with left:
    df = pd.DataFrame(R.legend_swatches(pattern))
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Hex": st.column_config.TextColumn("Swatch"),
            "% of pattern": st.column_config.ProgressColumn(
                "% of pattern", min_value=0.0,
                max_value=float(df["% of pattern"].max()), format="%.1f%%"),
        },
    )
    st.caption("Skein figures are estimates only — technique, fabric and "
               "waste all change real usage.")

with right:
    st.markdown("**Replace a thread**")
    which = st.selectbox(
        "Pattern color",
        range(len(pattern.colors)),
        format_func=lambda i: (f"{pattern.colors[i].symbol}  "
                               f"{pattern.colors[i].floss.number} — "
                               f"{pattern.colors[i].floss.name}"),
    )
    new = st.selectbox("Replace with",
                       [f"{f.number} — {f.name}" for f in palette])
    c1, c2 = st.columns(2)
    if c1.button("Apply swap", use_container_width=True):
        st.session_state.setdefault("swaps", {})[which] = new.split(" — ")[0]
        st.rerun()
    if c2.button("Clear swaps", use_container_width=True):
        st.session_state["swaps"] = {}
        st.rerun()

# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------

st.subheader("Download")
e1, e2, e3 = st.columns(3)

with e1:
    title = st.text_input("Pattern title", "My Cross Stitch Pattern")
    pagesize = st.selectbox("Page size", ["A4", "Letter"])
with e2:
    strands = st.selectbox("Strands used", [1, 2, 3, 4], index=1)
    chart_style = st.selectbox("PDF chart style",
                               ["Black & white symbols", "Symbols over color"])
with e3:
    st.checkbox("Large-print charts", key="large_print")
    cells = st.slider("Stitches per chart page", 30, 70, 50, 5)

d1, d2, d3 = st.columns(3)

png_buf = io.BytesIO()
R.stitch_simulation(pattern, scale=12).save(png_buf, format="PNG")
d1.download_button("Download preview PNG", png_buf.getvalue(),
                   "pattern_preview.png", "image/png",
                   use_container_width=True)

chart_buf = io.BytesIO()
R.symbol_chart(pattern, over_color=(chart_style == "Symbols over color"),
               large_print=st.session_state.get("large_print", False)
               ).save(chart_buf, format="PNG")
d2.download_button("Download chart PNG", chart_buf.getvalue(),
                   "pattern_chart.png", "image/png",
                   use_container_width=True)

if d3.button("Build pattern PDF", type="primary", use_container_width=True):
    with st.spinner("Laying out pages…"):
        pdf = build_pdf(pattern, title=title, pagesize_name=pagesize,
                        strands=strands,
                        over_color=(chart_style == "Symbols over color"),
                        cells_per_page=cells)
    st.session_state["pdf"] = pdf

if st.session_state.get("pdf"):
    st.download_button("Download pattern PDF", st.session_state["pdf"],
                       f"{title.replace(' ', '_')}.pdf", "application/pdf",
                       type="primary")

st.divider()
st.caption(
    "Cross stitch requires deliberate simplification — a converted photo is an "
    "interpretation, not a reproduction. Adjust detail, colors and size until "
    "the chart reads well at stitching scale."
)
