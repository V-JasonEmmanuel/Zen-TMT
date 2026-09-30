"""Builds the showcase sample set (all fictional, for demonstrating every feature):

  InvoiceFlow_Showcase.docx     document with every kind of content the planner turns into slides:
                                summary, problem, architecture (+ figure), workflow steps, tech stack,
                                timeline, results table (-> chart / KPIs), comparison, client quote,
                                risks, recommendations, conclusion
  demo_invoiceflow.mp4          25 s product demo screen recording (5 screens) - frame-by-frame narration
  narration_script.md           a script with "## Slide N" markers (optional script feature)
  background_music.mp3          30 s calm music bed, generated here (loop / fade / ducking demo)
  architecture_diagram.png      the Figure 1 image; also usable as an extra image in the video
  brand_backdrop.png            an extra still for the video timeline (Ken Burns / crop demo)

Run:  python samples/make_showcase.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

INDIGO, BLUE, CORAL, TEAL, INK, GREY = "#10005D", "#3A57A7", "#F04E45", "#00B0C0", "#1A1A1A", "#6D6E71"


def _font(size: int, bold: bool = False):
    for name in (("arialbd.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf") if bold else ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def architecture_png(path: Path) -> Path:
    W, H = 1600, 800
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    d.text((60, 40), "InvoiceFlow architecture", font=_font(40, True), fill=INDIGO)
    boxes = ["Upload Service", "Extraction Engine", "Rules Engine", "ERP Connector"]
    bw, bh, y = 300, 130, 300
    xs = [60 + i * 385 for i in range(4)]
    for i, (x, name) in enumerate(zip(xs, boxes)):
        d.rectangle((x, y, x + bw, y + bh), fill=INDIGO)
        tw = d.textlength(name, font=_font(30, True))
        d.text((x + (bw - tw) / 2, y + 45), name, font=_font(30, True), fill="white")
        if i < 3:
            d.line((x + bw + 8, y + bh / 2, x + 377, y + bh / 2), fill=BLUE, width=6)
            d.polygon([(x + 377, y + bh / 2), (x + 360, y + bh / 2 - 12), (x + 360, y + bh / 2 + 12)], fill=BLUE)
    # review console below the rules engine
    rx = xs[2]
    d.rectangle((rx, 560, rx + bw, 560 + bh), fill=BLUE)
    tw = d.textlength("Review Console", font=_font(30, True))
    d.text((rx + (bw - tw) / 2, 605), "Review Console", font=_font(30, True), fill="white")
    d.line((rx + bw / 2, y + bh + 6, rx + bw / 2, 552), fill=CORAL, width=6)
    d.text((60, 720), "Invoices above the approval threshold are routed to the Review Console.", font=_font(26), fill=GREY)
    im.save(path)
    return path


def brand_backdrop(path: Path) -> Path:
    from backend.branding.presets import apply_preset
    from backend.branding.theme import load_theme

    try:
        from backend.branding.social import fluid_gradient

        t = apply_preset(load_theme("zensar"), "zensar_experience")
        im = Image.open(fluid_gradient(t, 1920, 1080, seed=21)).convert("RGB")
    except Exception:
        im = Image.new("RGB", (1920, 1080), INDIGO)
    d = ImageDraw.Draw(im)
    d.text((140, 420), "InvoiceFlow pilot", font=_font(96, True), fill="white")
    d.text((140, 560), "Finance operations, 2026", font=_font(52), fill="white")
    im.save(path)
    return path


def showcase_docx(path: Path, figure: Path) -> Path:
    import docx
    from docx.shared import Inches

    doc = docx.Document()
    doc.add_heading("InvoiceFlow: Intelligent Accounts-Payable Automation", 0)
    doc.add_paragraph("Sample case study for Zensar Content Studio. The company, product and all figures in this document are "
                      "fictional and exist only to demonstrate the features of the application.").italic = True

    doc.add_heading("Executive summary", 1)
    doc.add_paragraph("InvoiceFlow automates accounts-payable invoice processing for a mid-size manufacturer. Uploaded PDF "
                      "invoices are read, key fields are extracted and invoices under the approval threshold are approved "
                      "automatically. In a six-month pilot, 86% of invoices were approved without manual work, the average "
                      "processing time fell from 9 minutes to 42 seconds per invoice and late-payment penalties dropped by 71%.")

    doc.add_heading("Background and problem", 1)
    doc.add_paragraph("Before the pilot the finance team keyed every invoice by hand. The main challenges were:")
    for t in ("Manual data entry caused errors in 6% of invoices.",
              "Invoices waited an average of 11 days for approval.",
              "Month-end closing needed three extra working days.",
              "The team had no single view of invoice status."):
        doc.add_paragraph(t, style="List Bullet")

    doc.add_heading("Solution overview", 1)
    doc.add_paragraph("InvoiceFlow combines document understanding, business rules and ERP integration in one service. Finance "
                      "staff only review exceptions, and every decision is recorded for audit.")

    doc.add_heading("Architecture", 1)
    doc.add_paragraph("The platform has four core components and a review console. The Upload Service receives PDF invoices by "
                      "e-mail or web upload. The Extraction Engine reads the vendor, invoice number, dates and amounts. The Rules "
                      "Engine applies the approval threshold and vendor rules. The ERP Connector exports approved invoices to SAP "
                      "S/4HANA. Invoices above the threshold go to the Review Console.")
    doc.add_picture(str(figure), width=Inches(6.0))
    doc.add_paragraph("Figure 1: InvoiceFlow architecture", style="Caption")

    doc.add_heading("Workflow", 1)
    doc.add_paragraph("Each invoice moves through the same pipeline:")
    for t in ("Receive: the Upload Service collects the PDF invoice from e-mail or the web portal.",
              "Extract: the Extraction Engine reads vendor, invoice number, dates and amount.",
              "Validate: the Rules Engine checks the amount against the approval threshold.",
              "Review: invoices above the threshold are routed to an analyst in the Review Console.",
              "Export: approved invoices are posted to SAP S/4HANA through the ERP Connector."):
        doc.add_paragraph(t, style="List Number")

    doc.add_heading("Technology stack", 1)
    for t in ("Python services with FastAPI for the Upload and Rules services.",
              "A local document-understanding model for field extraction.",
              "PostgreSQL for invoice records and the audit trail.",
              "SAP S/4HANA integration through standard OData APIs."):
        doc.add_paragraph(t, style="List Bullet")

    doc.add_heading("Implementation timeline", 1)
    for t in ("Phase 1 (January 2026): discovery and process mapping with the finance team.",
              "Phase 2 (February 2026): extraction model tuned on 2,000 historical invoices.",
              "Phase 3 (March 2026): rules engine and ERP connector built and tested.",
              "Phase 4 (April to June 2026): pilot with three business units and weekly reviews."):
        doc.add_paragraph(t, style="List Bullet")

    doc.add_heading("Results", 1)
    doc.add_paragraph("The pilot met every target. 86% of invoices were approved automatically, processing time fell to 42 seconds "
                      "per invoice, data-entry errors fell to 0.4% and month-end closing became 3 days faster.")
    rows = [("Metric", "Before", "After"), ("Processing time (minutes)", "9.0", "0.7"), ("Error rate (%)", "6.0", "0.4"),
            ("Approval wait (days)", "11", "2"), ("Auto-approved (%)", "0", "86")]
    table = doc.add_table(rows=len(rows), cols=3)
    table.style = "Table Grid"
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            table.cell(r, c).text = v
    doc.add_paragraph("Table 1: Pilot results before and after InvoiceFlow", style="Caption")
    doc.add_paragraph("Invoices processed per month during the pilot:")
    months = [("Month", "Invoices"), ("January", "820"), ("February", "910"), ("March", "1,040"), ("April", "1,180"),
              ("May", "1,260"), ("June", "1,340")]
    t2 = doc.add_table(rows=len(months), cols=2)
    t2.style = "Table Grid"
    for r, row in enumerate(months):
        for c, v in enumerate(row):
            t2.cell(r, c).text = v
    doc.add_paragraph("Table 2: Monthly invoice volume", style="Caption")

    doc.add_heading("Before and after", 1)
    doc.add_paragraph("Compared with the manual process, InvoiceFlow changes how the team works. Before, analysts keyed every "
                      "invoice and chased approvals by e-mail. After, analysts only handle exceptions, approvals are tracked in "
                      "one console, and vendors are paid on time. Manual processing versus automated processing: 9 minutes "
                      "versus 42 seconds per invoice.")

    doc.add_heading("Client perspective", 1)
    doc.add_paragraph("\"InvoiceFlow gave our finance team its time back. We now spend our days on vendor relationships instead "
                      "of data entry.\" - Head of Finance Operations, pilot customer", style="Intense Quote")

    doc.add_heading("Risks and mitigations", 1)
    for t in ("Unusual invoice layouts: low-confidence fields are always sent for review.",
              "ERP downtime: approved invoices are queued and retried automatically.",
              "Change resistance: analysts were trained in two short workshops."):
        doc.add_paragraph(t, style="List Bullet")

    doc.add_heading("Recommendations and next steps", 1)
    for t in ("Roll out to the remaining five business units in the next quarter.",
              "Add purchase-order matching to raise automatic approval above 90%.",
              "Publish a monthly dashboard of processing time and exceptions."):
        doc.add_paragraph(t, style="List Number")

    doc.add_heading("Conclusion", 1)
    doc.add_paragraph("InvoiceFlow turned invoice processing from a manual bottleneck into a measured, largely automatic "
                      "pipeline. The pilot results support a full rollout.")

    doc.add_heading("References", 1)
    doc.add_paragraph("Pilot measurement log, January to June 2026 (fictional).")
    doc.save(path)
    return path


def music(path: Path, ff: str, seconds: int = 30) -> Path:
    """A soft four-chord pad (Cmaj7 - Am7 - Fmaj7 - G), generated - no third-party audio."""
    chords = [(261.63, 329.63, 392.0, 493.88), (220.0, 261.63, 329.63, 392.0), (174.61, 220.0, 261.63, 329.63), (196.0, 246.94, 293.66, 392.0)]
    seg = seconds / len(chords)
    expr = []
    for i, ch in enumerate(chords):
        tone = "+".join(f"sin(2*PI*{f}*t)" for f in ch)
        expr.append(f"between(t,{i * seg:.2f},{(i + 1) * seg:.2f})*({tone})")
    e = "0.16*(" + "+".join(expr) + ")*(0.85+0.15*sin(2*PI*0.25*t))"
    subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"aevalsrc='{e}':s=44100:d={seconds}",
                    "-af", f"lowpass=f=1800,aecho=0.8:0.7:60:0.3,afade=t=in:d=2,afade=t=out:st={seconds - 3}:d=3",
                    "-b:a", "96k", str(path)], check=True)
    return path


SCRIPT = """# Narration script (optional)
# Use it in the New Project wizard (Video narration > Script) or in the video editor.
# "## Slide N" targets a slide; unmarked text would be spread across the video.

## Slide 1
Welcome. This is InvoiceFlow, an intelligent accounts-payable service, presented with Zensar Content Studio.

## Slide 2
In short: most invoices now approve themselves, and each one takes seconds instead of minutes.
"""


def main() -> None:
    from backend.rendering.video.ffmpeg import find_ffmpeg
    from tests.fixtures.make_demo_video import make_demo_video

    ff = find_ffmpeg()
    fig = architecture_png(HERE / "architecture_diagram.png")
    showcase_docx(HERE / "InvoiceFlow_Showcase.docx", fig)
    brand_backdrop(HERE / "brand_backdrop.png")
    (HERE / "narration_script.md").write_text(SCRIPT, encoding="utf-8")
    if ff:
        make_demo_video(HERE / "demo_invoiceflow.mp4", ff)
        music(HERE / "background_music.mp3", ff)
    else:
        print("FFmpeg not found: the demo video and music were not generated.")
    for p in sorted(HERE.iterdir()):
        if p.suffix != ".py":
            print(f"{p.name:32} {p.stat().st_size / 1024:8.0f} KB")


if __name__ == "__main__":
    main()
