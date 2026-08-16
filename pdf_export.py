"""
Multi-page vector PDF export.

The chart is drawn as vector rectangles and text (not a rasterised image) so
symbols stay crisp at any zoom or print size.
"""

from __future__ import annotations

import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from stitch_engine import Pattern

PAGESIZES = {"A4": A4, "Letter": LETTER}

MARGIN = 15 * mm
OVERLAP = 2          # stitches of overlap between chart pages


def _header(c: canvas.Canvas, W: float, H: float, title: str, sub: str) -> None:
    c.setFillColor(colors.HexColor("#1f2933"))
    c.setFont("Helvetica-Bold", 13)
    c.drawString(MARGIN, H - MARGIN + 4, title)
    c.setFont("Helvetica", 8.5)
    c.setFillColor(colors.HexColor("#6b7280"))
    c.drawRightString(W - MARGIN, H - MARGIN + 4, sub)
    c.setStrokeColor(colors.HexColor("#d1d5db"))
    c.line(MARGIN, H - MARGIN - 2, W - MARGIN, H - MARGIN - 2)


def _footer(c: canvas.Canvas, W: float, text: str) -> None:
    c.setFont("Helvetica", 7.5)
    c.setFillColor(colors.HexColor("#9ca3af"))
    c.drawCentredString(W / 2, MARGIN - 8 * mm, text)


def build_pdf(
    pattern: Pattern,
    title: str = "Cross Stitch Pattern",
    pagesize_name: str = "A4",
    strands: int = 2,
    over_color: bool = False,
    cells_per_page: int = 50,
) -> bytes:
    pagesize = PAGESIZES.get(pagesize_name, A4)
    W, H = pagesize
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=pagesize)
    c.setTitle(title)

    fw_in, fh_in = pattern.finished_inches
    fw_cm, fh_cm = pattern.finished_cm
    est = pattern.skeins_estimate(strands)

    # ---------------- Cover ----------------
    _header(c, W, H, title, date.today().isoformat())
    y = H - MARGIN - 20 * mm

    c.setFillColor(colors.HexColor("#111827"))
    c.setFont("Helvetica-Bold", 20)
    c.drawString(MARGIN, y, title)
    y -= 12 * mm

    c.setFont("Helvetica", 10.5)
    c.setFillColor(colors.HexColor("#374151"))
    rows = [
        ("Stitch count", f"{pattern.stitch_w} W x {pattern.stitch_h} H"
                         f"  ({pattern.total_stitches:,} stitches)"),
        ("Fabric count", f"{pattern.fabric_count:g} count"),
        ("Finished size", f"{fw_in:.1f} x {fh_in:.1f} in"
                          f"   /   {fw_cm:.1f} x {fh_cm:.1f} cm"),
        ("Thread colors", f"{len(pattern.colors)}"),
        ("Strands", f"{strands} over 1"),
    ]
    for label, val in rows:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(MARGIN, y, label)
        c.setFont("Helvetica", 10)
        c.drawString(MARGIN + 38 * mm, y, val)
        y -= 6.5 * mm

    y -= 4 * mm
    # Thumbnail of the finished design, drawn as vector cells.
    thumb_w = W - 2 * MARGIN
    cell = min(thumb_w / pattern.stitch_w, (y - MARGIN - 30 * mm) / pattern.stitch_h)
    ox = MARGIN
    oy = y - pattern.stitch_h * cell
    for gy in range(pattern.stitch_h):
        for gx in range(pattern.stitch_w):
            r, g, b = pattern.colors[int(pattern.grid[gy, gx])].floss.rgb
            c.setFillColorRGB(r / 255, g / 255, b / 255)
            c.rect(ox + gx * cell, oy + (pattern.stitch_h - 1 - gy) * cell,
                   cell, cell, stroke=0, fill=1)

    c.setFont("Helvetica-Oblique", 8)
    c.setFillColor(colors.HexColor("#6b7280"))
    c.drawString(
        MARGIN, MARGIN,
        "Cross stitch requires deliberate simplification; this chart is an "
        "interpretation of the photo, not a reproduction of it.",
    )
    c.showPage()

    # ---------------- Color key ----------------
    _header(c, W, H, "Color key", f"{len(pattern.colors)} threads")
    y = H - MARGIN - 14 * mm
    headers = ["", "Sym", "No.", "Name", "Stitches", "%", "Skeins*"]
    xs = [MARGIN, MARGIN + 10 * mm, MARGIN + 20 * mm, MARGIN + 34 * mm,
          W - MARGIN - 52 * mm, W - MARGIN - 30 * mm, W - MARGIN - 16 * mm]
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(colors.HexColor("#374151"))
    for hx, ht in zip(xs, headers):
        c.drawString(hx, y, ht)
    y -= 5 * mm

    for pc in pattern.colors:
        if y < MARGIN + 14 * mm:
            _footer(c, W, "*Skein figures are estimates. Technique and waste vary.")
            c.showPage()
            _header(c, W, H, "Color key (continued)", "")
            y = H - MARGIN - 14 * mm
        r, g, b = pc.floss.rgb
        c.setFillColorRGB(r / 255, g / 255, b / 255)
        c.setStrokeColor(colors.HexColor("#9ca3af"))
        c.rect(xs[0], y - 1, 6 * mm, 4.2 * mm, stroke=1, fill=1)
        c.setFillColor(colors.HexColor("#111827"))
        c.setFont("Helvetica-Bold", 9)
        c.drawString(xs[1], y, pc.symbol)
        c.setFont("Helvetica", 8.5)
        c.drawString(xs[2], y, pc.floss.number)
        c.drawString(xs[3], y, pc.floss.name[:40])
        c.drawRightString(xs[4] + 16 * mm, y, f"{pc.count:,}")
        c.drawRightString(xs[5] + 10 * mm, y, f"{pc.percent:.1f}")
        c.drawRightString(xs[6] + 12 * mm, y, f"{est[pc.floss.number]:.2f}")
        y -= 5 * mm

    _footer(c, W, "*Skein figures are estimates. Technique and waste vary.")
    c.showPage()

    # ---------------- Chart pages ----------------
    avail_w = W - 2 * MARGIN - 8 * mm
    avail_h = H - 2 * MARGIN - 16 * mm
    cols = cells_per_page
    cell = min(avail_w / cols, avail_h / cols)
    rows_per = int(avail_h / cell)

    x_pages = list(range(0, pattern.stitch_w, cols - OVERLAP))
    y_pages = list(range(0, pattern.stitch_h, rows_per - OVERLAP))
    total_pages = len(x_pages) * len(y_pages)

    page_no = 0
    for py, gy0 in enumerate(y_pages):
        for px, gx0 in enumerate(x_pages):
            page_no += 1
            gx1 = min(gx0 + cols, pattern.stitch_w)
            gy1 = min(gy0 + rows_per, pattern.stitch_h)
            nx, ny = gx1 - gx0, gy1 - gy0

            _header(c, W, H, f"Chart page {page_no} of {total_pages}",
                    f"Section {px + 1} across, {py + 1} down  |  "
                    f"stitches {gx0 + 1}-{gx1} x {gy0 + 1}-{gy1}")

            ox = MARGIN + 8 * mm
            oy = H - MARGIN - 10 * mm - ny * cell

            for j in range(ny):
                for i in range(nx):
                    idx = int(pattern.grid[gy0 + j, gx0 + i])
                    pc = pattern.colors[idx]
                    X = ox + i * cell
                    Y = oy + (ny - 1 - j) * cell
                    if over_color:
                        r, g, b = pc.floss.rgb
                        c.setFillColorRGB(r / 255, g / 255, b / 255)
                        c.rect(X, Y, cell, cell, stroke=0, fill=1)
                        lum = (r + g + b) / 3
                        c.setFillColor(colors.white if lum < 110 else colors.black)
                    else:
                        c.setFillColor(colors.black)
                    c.setFont("Helvetica-Bold", cell * 0.66)
                    c.drawCentredString(X + cell / 2, Y + cell * 0.28, pc.symbol)

            # Grid: light every stitch, heavy every 10 aligned to absolute coords.
            for i in range(nx + 1):
                heavy = (gx0 + i) % 10 == 0
                c.setStrokeColor(colors.HexColor("#333333") if heavy
                                 else colors.HexColor("#c8c8c8"))
                c.setLineWidth(1.1 if heavy else 0.3)
                c.line(ox + i * cell, oy, ox + i * cell, oy + ny * cell)
            for j in range(ny + 1):
                heavy = (gy0 + j) % 10 == 0
                c.setStrokeColor(colors.HexColor("#333333") if heavy
                                 else colors.HexColor("#c8c8c8"))
                c.setLineWidth(1.1 if heavy else 0.3)
                c.line(ox, oy + j * cell, ox + nx * cell, oy + j * cell)

            # Coordinate rulers every 10 stitches.
            c.setFont("Helvetica", 5.5)
            c.setFillColor(colors.HexColor("#4b5563"))
            for i in range(nx + 1):
                if (gx0 + i) % 10 == 0:
                    c.drawCentredString(ox + i * cell, oy + ny * cell + 2.5,
                                        str(gx0 + i))
            for j in range(ny + 1):
                if (gy0 + j) % 10 == 0:
                    c.drawRightString(ox - 1.5, oy + (ny - j) * cell - 1.8,
                                      str(gy0 + j))

            _footer(c, W, f"{title}  |  overlap {OVERLAP} stitches between pages")
            c.showPage()

    c.save()
    return buf.getvalue()
