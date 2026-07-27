# error_pdf.py — "Quaderno degli Errori" PDF
# Renders data/error_db.json as a personal error notebook: pattern summary
# (which categories Kevin gets wrong most) + every correction grouped by category.

import json
from pathlib import Path
from datetime import datetime
from collections import Counter

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)

# Path ancorati al progetto, non alla cwd (vedi do/base/paths.py). Erano
# `Path("data/...")`: lanciare da un'altra cartella creava directory vuote nel
# posto sbagliato, in silenzio. Questo modulo resta il generatore ReportLab
# finche' non viene consolidato in do/uscite/ — vedi la nota in do/uscite/pdf.py.
from do.base.paths import ERROR_DB, PDFS  # noqa: E402

OUT = PDFS / "Quaderno_Errori.pdf"

C_NAVY = colors.HexColor("#0d2137")
C_BLUE = colors.HexColor("#1565c0")
C_RED = colors.HexColor("#c62828")
C_GREEN = colors.HexColor("#2e7d32")
C_GRAY = colors.HexColor("#546e7a")
C_LGRAY = colors.HexColor("#eceff1")
C_LIGHT = colors.HexColor("#f0f7ff")
C_YELLOW = colors.HexColor("#fff8e1")

W = A4[0] - 4 * cm


def _S(name, **kw):
    return ParagraphStyle(name, **kw)


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def generate_error_pdf(out: Path = OUT) -> Path:
    if not ERROR_DB.exists():
        raise FileNotFoundError("data/error_db.json non trovato — esegui error_extractor.py")
    db = json.loads(ERROR_DB.read_text(encoding="utf-8"))
    errors = db.get("errors", [])
    n_lessons = len(db.get("lessons_processed", []))

    by_cat = Counter(e.get("category", "Sonstiges") for e in errors)
    ordered_cats = [c for c, _ in by_cat.most_common()]

    out.parent.mkdir(exist_ok=True)
    doc = SimpleDocTemplate(
        str(out), pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=1.6 * cm, bottomMargin=1.6 * cm,
        title="Quaderno degli Errori", author="DeutschOps",
    )
    story = []

    # ── Header band ──────────────────────────────────────────────
    head = Table([[Paragraph(
        "<b>Quaderno degli Errori</b>", _S("h", fontSize=22, textColor=colors.white,
                                           leading=26))],
        [Paragraph(f"Kevin · A2→B1 · {len(errors)} correzioni su {n_lessons} lezioni · "
                   f"{datetime.now():%d %b %Y}",
                   _S("hs", fontSize=9.5, textColor=colors.HexColor("#90caf9")))]],
        colWidths=[W])
    head.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_NAVY),
        ("LEFTPADDING", (0, 0), (-1, -1), 16),
        ("TOPPADDING", (0, 0), (0, 0), 14),
        ("BOTTOMPADDING", (0, 1), (0, 1), 14),
    ]))
    story += [head, Spacer(1, 14)]

    # ── Pattern summary ──────────────────────────────────────────
    story.append(Paragraph("I tuoi pattern ricorrenti",
                           _S("st", fontSize=13, textColor=C_NAVY, spaceAfter=6)))
    maxn = by_cat.most_common(1)[0][1] if by_cat else 1
    rows = []
    for cat, n in by_cat.most_common():
        bar = "█" * max(1, round(18 * n / maxn))
        rows.append([
            Paragraph(f"<b>{_esc(cat)}</b>", _S("c", fontSize=9.5, textColor=C_NAVY)),
            Paragraph(str(n), _S("n", fontSize=9.5, textColor=C_RED, alignment=TA_CENTER)),
            Paragraph(f'<font color="#1565c0">{bar}</font>', _S("b", fontSize=9)),
        ])
    summ = Table(rows, colWidths=[4.2 * cm, 1.3 * cm, W - 5.5 * cm])
    summ.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, C_LIGHT]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [summ, Spacer(1, 6),
              Paragraph("Concentrati sulle categorie in alto: sono ciò che ti separa dal B1.",
                        _S("tip", fontSize=8.5, textColor=C_GRAY)),
              Spacer(1, 12)]

    # ── Errors by category ───────────────────────────────────────
    for cat in ordered_cats:
        cat_errs = [e for e in errors if e.get("category") == cat]
        block = [HRFlowable(width="100%", color=C_BLUE, thickness=1.4, spaceAfter=4),
                 Paragraph(f"<b>{_esc(cat)}</b> &nbsp;<font size=8 color='#546e7a'>"
                           f"({len(cat_errs)})</font>",
                           _S("ch", fontSize=12, textColor=C_BLUE, spaceAfter=4))]
        story.append(KeepTogether(block))
        for e in cat_errs:
            wrong = _esc(e.get("kevin_said", "")) or "<i>(forma implicita)</i>"
            corr = _esc(e.get("correction", ""))
            rule = _esc(e.get("rule", ""))
            expl = _esc(e.get("explanation_en", ""))
            ex = _esc(e.get("example_correct", ""))
            ld = _esc(e.get("lesson_date", "")).replace("-stefanie", "")
            inner = (
                f'<font color="#c62828">✗ {wrong}</font> &nbsp;→&nbsp; '
                f'<font color="#2e7d32"><b>✓ {corr}</b></font><br/>'
                f'<b>{rule}</b> <font size=7 color="#90a4ae">· {ld}</font><br/>'
                f'<font color="#546e7a">{expl}</font>'
            )
            if ex:
                inner += f'<br/><i>„{ex}“</i>'
            card = Table([[Paragraph(inner, _S("e", fontSize=9, leading=13))]],
                         colWidths=[W])
            card.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), C_YELLOW),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LINEBELOW", (0, 0), (-1, -1), 3, colors.white),
            ]))
            story += [card, Spacer(1, 3)]
        story.append(Spacer(1, 8))

    doc.build(story)
    print(f"✅ Quaderno errori: {out} ({len(errors)} correzioni)")
    return out


if __name__ == "__main__":
    generate_error_pdf()
