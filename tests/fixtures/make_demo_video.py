"""Synthetic product-demo screen recording for tests: five app screens with a moving cursor."""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H, FPS, SECONDS = 1280, 720, 15, 5


def _font(size: int):
    for name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _chrome(d: ImageDraw.ImageDraw, title: str, active: str) -> None:
    d.rectangle((0, 0, W, 56), fill=(16, 0, 93))
    d.text((24, 16), "InvoiceFlow", font=_font(24), fill="white")
    d.text((W - 260, 18), "Signed in as analyst", font=_font(16), fill=(210, 220, 240))
    d.rectangle((0, 56, 200, H), fill=(240, 242, 247))
    for i, item in enumerate(("Dashboard", "Upload", "Results", "Settings")):
        y = 90 + i * 44
        if item == active:
            d.rectangle((0, y - 8, 200, y + 28), fill=(211, 225, 244))
        d.text((24, y), item, font=_font(18), fill=(26, 26, 26))
    d.text((230, 76), title, font=_font(30), fill=(26, 26, 26))


def screen(kind: str) -> Image.Image:
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    if kind == "login":
        d.rectangle((0, 0, W, H), fill=(240, 242, 247))
        d.rectangle((440, 160, 840, 540), fill="white", outline=(200, 200, 210))
        d.text((520, 190), "InvoiceFlow", font=_font(34), fill=(16, 0, 93))
        d.text((480, 250), "Sign in to your workspace", font=_font(18), fill=(90, 90, 90))
        for i, lab in enumerate(("Email", "Password")):
            d.text((480, 300 + i * 70), lab, font=_font(16), fill=(60, 60, 60))
            d.rectangle((480, 322 + i * 70, 800, 352 + i * 70), outline=(180, 180, 190))
        d.rectangle((480, 460, 800, 500), fill=(58, 87, 167))
        d.text((600, 470), "Sign in", font=_font(18), fill="white")
        return im
    if kind == "dashboard":
        _chrome(d, "Dashboard", "Dashboard")
        for i, (lab, val) in enumerate((("Invoices processed", "1,248"), ("Auto-approved", "86%"), ("Avg. processing time", "42 s"))):
            x = 230 + i * 330
            d.rectangle((x, 130, x + 300, 250), fill=(240, 242, 247))
            d.text((x + 20, 150), val, font=_font(40), fill=(16, 0, 93))
            d.text((x + 20, 205), lab, font=_font(16), fill=(90, 90, 90))
        d.text((230, 280), "Invoices per week", font=_font(20), fill=(26, 26, 26))
        for i, h in enumerate((120, 160, 140, 210, 250, 230)):
            d.rectangle((250 + i * 120, 600 - h, 320 + i * 120, 600), fill=(58, 87, 167))
        return im
    if kind == "upload":
        _chrome(d, "Upload invoices", "Upload")
        d.rectangle((260, 150, 1220, 430), outline=(58, 87, 167), width=3)
        d.text((560, 250), "Drop PDF invoices here", font=_font(28), fill=(58, 87, 167))
        d.text((600, 300), "or click to browse", font=_font(18), fill=(90, 90, 90))
        for i, f in enumerate(("acme_march.pdf  - extracting fields...", "globex_0421.pdf  - queued")):
            d.text((270, 470 + i * 40), f, font=_font(18), fill=(26, 26, 26))
        d.rectangle((270, 555, 1000, 570), fill=(230, 230, 235))
        d.rectangle((270, 555, 720, 570), fill=(240, 78, 69))
        return im
    if kind == "results":
        _chrome(d, "Extraction results", "Results")
        cols = ("Vendor", "Invoice no.", "Amount", "Status")
        rows = (("Acme Corp", "INV-2041", "$4,120.00", "Approved"), ("Globex", "G-0421", "$980.50", "Needs review"),
                ("Initech", "IT-771", "$12,300.00", "Approved"))
        for j, c in enumerate(cols):
            d.rectangle((230 + j * 240, 140, 470 + j * 240, 180), fill=(16, 0, 93))
            d.text((245 + j * 240, 150), c, font=_font(18), fill="white")
        for i, r in enumerate(rows):
            for j, v in enumerate(r):
                d.text((245 + j * 240, 200 + i * 50), v, font=_font(18), fill=(200, 60, 50) if v == "Needs review" else (26, 26, 26))
        d.rectangle((230, 400, 470, 440), fill=(58, 87, 167))
        d.text((255, 410), "Export to ERP", font=_font(18), fill="white")
        return im
    _chrome(d, "Settings", "Settings")
    for i, (lab, val) in enumerate((("Approval threshold", "$5,000"), ("ERP connector", "SAP S/4HANA"), ("Notifications", "Email"))):
        d.text((250, 150 + i * 70), lab, font=_font(20), fill=(26, 26, 26))
        d.rectangle((560, 145 + i * 70, 900, 180 + i * 70), outline=(180, 180, 190))
        d.text((575, 152 + i * 70), val, font=_font(18), fill=(60, 60, 60))
    return im


def make_demo_video(out: Path, ffmpeg: str) -> Path:
    frames_dir = out.parent / (out.stem + "_frames")
    frames_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for kind in ("login", "dashboard", "upload", "results", "settings"):
        base = screen(kind)
        for i in range(SECONDS * FPS):
            f = base.copy()
            d = ImageDraw.Draw(f)
            cx, cy = 600 + int(250 * (i / (SECONDS * FPS))), 420 - int(120 * (i / (SECONDS * FPS)))
            d.polygon([(cx, cy), (cx + 14, cy + 22), (cx + 5, cy + 20), (cx, cy + 28)], fill="black")
            f.save(frames_dir / f"f{n:05d}.png")
            n += 1
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(FPS), "-i", str(frames_dir / "f%05d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], check=True)
    for p in frames_dir.glob("*.png"):
        p.unlink()
    frames_dir.rmdir()
    return out


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from backend.rendering.video.ffmpeg import find_ffmpeg

    print(make_demo_video(Path(__file__).parent / "demo_invoiceflow.mp4", find_ffmpeg()))
