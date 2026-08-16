# Photo to Cross Stitch Converter

Turn a photo into a usable cross-stitch pattern: stitch grid, floss-matched
palette, symbol chart, and a printable multi-page PDF.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Files

| File | Purpose |
|---|---|
| `app.py` | Streamlit UI |
| `stitch_engine.py` | LAB color, quantization, floss matching, symbols (UI-free) |
| `renderers.py` | Stitch simulation, symbol charts, PNG export |
| `pdf_export.py` | Vector multi-page PDF |
| `palette_starter.csv` | Thread palette data |

## Design notes

**Color matching is done in CIE L\*a\*b\*, not RGB.** Clustering and
nearest-thread matching both run in LAB with Delta E distance, which is why
skin tones and gradients hold together instead of banding into unrelated hues.

**Downsampling uses BOX averaging, not nearest-neighbour.** Each stitch is the
average of the photo region it covers. This is the difference between a
conversion and a pixelate filter.

**Requested vs delivered color count.** Clusters are assigned threads greedily,
largest first, preferring an unused thread. Two clusters share a thread only
when every alternative is more than 6 Delta E worse. So asking for 32 may yield
~24 — that is the engine declining to pad the legend with threads you would not
be able to tell apart on fabric.

**Locked threads are guaranteed, not preferred.** Each locked thread is
reserved to its best-matching cluster before general assignment runs.

**Caching.** `run_conversion` is keyed on pipeline inputs only, so changing
chart style, page size or title does not re-run the conversion.

## Palette licensing

`palette_starter.csv` is a starter set of ~270 common floss colors with generic
descriptive names. DMC color numbers are widely published as factual reference
data, but the names and numbering system are DMC's, and shade values here are
approximations, not calibrated measurements.

Before selling this, either swap in an independently maintained palette dataset
whose licensing you have confirmed, or license data from the manufacturer.
Nothing in the app hard-codes the palette — replacing the CSV is the only
change needed.

## Known limits

- Floss estimates are rough; label them as estimates in any commercial UI.
- Region cleanup / paint tools (Phase 3) are not built.
- Very large grids (>200k stitches) are slow to render in-browser.
