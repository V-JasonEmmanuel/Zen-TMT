"""Record the product demo video (no voice, on-screen captions) by driving the running app in Edge.

    python scripts/record_demo.py            # app must be running (start.bat) on http://127.0.0.1:8000
    -> docs/demo/raw/*.webm + docs/demo/scenes.json  (then: python scripts/edit_demo.py)

Uses Playwright with the installed Microsoft Edge (no browser download). Sample inputs come from samples/.
"""
from __future__ import annotations

import base64
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000"
OUT = ROOT / "docs" / "demo"
RAW = OUT / "raw"
W, H = 1440, 900

CURSOR_JS = """
(() => {
  if (window.__zcsCursor) return;
  const install = () => {
    if (!document.body) return setTimeout(install, 50);
    const c = document.createElement('div'); c.id = '__zcs_cursor';
    c.style.cssText = 'position:fixed;z-index:2147483647;width:22px;height:22px;border-radius:50%;' +
      'background:rgba(240,78,69,.55);border:2px solid #fff;box-shadow:0 0 0 2px rgba(16,0,93,.35);' +
      'pointer-events:none;transform:translate(-50%,-50%);transition:left .25s ease, top .25s ease;left:-50px;top:-50px';
    document.body.appendChild(c);
    window.addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
    window.addEventListener('mousedown', () => { c.style.background = 'rgba(240,78,69,.95)'; }, true);
    window.addEventListener('mouseup', () => { c.style.background = 'rgba(240,78,69,.55)'; }, true);
  };
  window.__zcsCursor = true; install();
})();
"""

CAPTION_JS = """
(text) => {
  let b = document.getElementById('__zcs_cap');
  if (!b) {
    b = document.createElement('div'); b.id = '__zcs_cap';
    b.style.cssText = 'position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:2147483646;max-width:1100px;' +
      'background:rgba(16,0,93,.92);color:#fff;font:600 21px/1.35 "Segoe UI",Arial,sans-serif;padding:14px 26px;' +
      'border-radius:14px;box-shadow:0 10px 30px rgba(0,0,0,.35);border-left:6px solid #F04E45;transition:opacity .3s';
    document.body.appendChild(b);
  }
  b.style.opacity = text ? '1' : '0';
  if (text) b.textContent = text;
}
"""


def card_html(title: str, subtitle: str, logo_b64: str, foot: str = "") -> str:
    return f"""<!doctype html><html><body style="margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
    background:radial-gradient(circle at 75% 30%,#3A57A7 0%,#10005D 55%,#07002e 100%);font-family:'Segoe UI',Arial,sans-serif;color:#fff">
    <div style="text-align:center;max-width:1100px;padding:40px">
      <img src="data:image/png;base64,{logo_b64}" style="height:64px;margin-bottom:40px">
      <div style="font-size:58px;font-weight:700;letter-spacing:-.5px">{title}</div>
      <div style="width:90px;height:7px;background:#F04E45;margin:28px auto"></div>
      <div style="font-size:26px;opacity:.92;line-height:1.5">{subtitle}</div>
      <div style="font-size:18px;opacity:.7;margin-top:40px">{foot}</div>
    </div></body></html>"""


class Demo:
    def __init__(self, page):
        self.page = page
        self.t0 = time.time()
        self.scenes: list[dict] = []

    def now(self) -> float:
        return round(time.time() - self.t0, 2)

    def scene(self, name: str, fast: bool = False):
        if self.scenes and "end" not in self.scenes[-1]:
            self.scenes[-1]["end"] = self.now()
        self.scenes.append({"name": name, "start": self.now(), "fast": fast})

    def cap(self, text: str, hold: float = 0):
        try:
            self.page.evaluate(CURSOR_JS)
            self.page.evaluate(CAPTION_JS, text)
        except Exception:
            pass
        if hold:
            self.page.wait_for_timeout(int(hold * 1000))

    def go(self, path: str, wait: float = 1.2):
        self.page.goto(BASE + path, wait_until="networkidle")
        self.page.wait_for_timeout(int(wait * 1000))
        self.cap("")

    def click(self, locator, pause: float = 0.6):
        loc = locator.first
        loc.scroll_into_view_if_needed()
        box = loc.bounding_box()
        if box:
            self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=12)
            self.page.wait_for_timeout(350)
        loc.click()
        self.page.wait_for_timeout(int(pause * 1000))

    def scroll(self, dy: int, steps: int = 8, pause: float = 0.12):
        for _ in range(steps):
            self.page.mouse.wheel(0, dy / steps)
            self.page.wait_for_timeout(int(pause * 1000))


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    for f in RAW.glob("*.webm"):
        f.unlink()
    logo = base64.b64encode((ROOT / "brands/zensar/assets/logo/zensar_logo_white.png").read_bytes()).decode()
    sample_doc = ROOT / "samples" / "InvoiceFlow_Showcase.docx"
    sample_paper = ROOT / "samples" / "papers" / "sample_ieee_two_column.pdf"
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(RAW),
                                  record_video_size={"width": W, "height": H}, device_scale_factor=1)
        ctx.add_init_script(CURSOR_JS)
        page = ctx.new_page()
        d = Demo(page)

        # 1. title
        d.scene("title")
        page.set_content(card_html("Zensar Content Studio", "Turn documents into presentations, videos, publisher-ready papers<br>and branded white papers - entirely on your own computer.",
                                   logo, "Offline AI  |  Local models  |  Your documents never leave the machine"))
        page.wait_for_timeout(6500)

        # 2. dashboard
        d.scene("dashboard")
        d.go("/")
        d.cap("The Dashboard: recent projects and the status of the local AI, models and tools.", 4.5)
        d.click(page.get_by_role("link", name=re.compile("Projects")))
        d.cap("Projects: every document turned into slides, visuals and a narrated video.", 3.5)

        # 3. a finished project
        d.scene("project")
        d.go("/projects/prj_fb72ec1a5449", 2.0)
        d.cap("A finished project: the editable PowerPoint generated from the uploaded document.", 3.0)
        d.scroll(500)
        page.wait_for_timeout(1500)
        d.scroll(-500)
        d.click(page.get_by_role("button", name=re.compile("^Images")))
        d.cap("Brand-styled visuals: architecture diagrams, workflows and charts from the document's own facts.", 4.0)
        d.click(page.get_by_role("button", name=re.compile("^Video editor")))
        d.cap("The video editor: narrated scenes with motion graphics, ready to render as MP4.", 4.0)
        d.click(page.get_by_role("button", name=re.compile("^Sources")))
        d.cap("Every statement is traceable to its source page - nothing is invented.", 3.5)

        # 4. research papers - live upload
        d.scene("papers-upload")
        d.go("/papers", 1.5)
        d.cap("Research Papers: convert a paper into a publisher's format. Uploading a sample IEEE paper...", 2.5)
        page.set_input_files("input[type=file]", str(sample_paper))
        page.wait_for_timeout(1200)
        d.click(page.get_by_role("button", name=re.compile("Springer Nature journal")))
        d.cap("Target format: Springer Nature. Citations, references and layout will be rebuilt.", 2.5)
        d.click(page.get_by_role("button", name=re.compile("Convert paper")))
        d.scene("papers-wait", fast=True)
        page.wait_for_url(re.compile(r"/papers/pap_"), timeout=60000)
        d.cap("Converting: reading the layout, structure, references and citations...", 0)
        page.get_by_text("Converted", exact=True).first.wait_for(timeout=15 * 60 * 1000)
        d.scene("papers-result")
        page.wait_for_timeout(1500)
        d.cap("Done: the paper in the publisher's layout, with a report of the publisher's checks.", 4.0)
        for tab, text in (("Structure", "The recognised structure: title, authors, abstract and every section."),
                          ("References", "Every reference parsed into fields and re-formatted in the official citation style."),
                          ("Report", "The report: what the publisher requires and how much of the text was preserved."),
                          ("Downloads", "Downloads: LaTeX project, Word, PDF and BibTeX.")):
            d.click(page.get_by_role("button", name=re.compile("^" + tab)))
            d.cap(text, 3.2)

        # 5. brand documents - live upload
        d.scene("brand-upload")
        d.go("/brand-docs", 1.5)
        d.cap("Brand Documents: any document becomes a branded white paper, designed like a reference PDF.", 3.5)
        d.click(page.get_by_text("Zensar White Paper", exact=True))
        d.cap("The template was learned from a real Zensar white paper: pages, colours, type, layout and artwork.", 3.5)
        page.locator("input[type=file]").nth(1).set_input_files(str(sample_doc))  # 2nd drop box: "Your document"
        page.wait_for_timeout(1000)
        d.scroll(700)
        d.cap("Length: match the reference. Long documents are condensed, short ones expanded, by the local AI.", 3.5)
        d.scroll(500)
        d.cap("Images for the content are generated on this computer with a local image model.", 3.0)
        d.click(page.get_by_role("button", name=re.compile("Create branded PDF")))
        d.scene("brand-wait", fast=True)
        page.wait_for_url(re.compile(r"/brand-docs/bdc_"), timeout=60000)
        d.cap("Creating: reading, fitting the length, writing image prompts, generating images, laying out pages...", 0)
        page.get_by_role("button", name=re.compile("Download PDF")).first.wait_for(timeout=60 * 60 * 1000)
        d.scene("brand-result")
        page.wait_for_timeout(2500)
        d.cap("The finished branded PDF, with a check that every word arrived.", 3.5)
        d.scroll(900)
        d.cap("The generated images and the prompts written from the document's content.", 4.0)
        d.scroll(-900)
        url = page.url
        did = url.rsplit("/", 1)[-1]
        meta = page.evaluate(f"fetch('/api/branddocs/{did}').then(r => r.json())")
        pages = meta.get("pages", [])
        gallery = "".join(f'<img src="{BASE}/api/branddocs/{did}/files/{p}" style="height:380px;margin:10px;box-shadow:0 8px 24px rgba(0,0,0,.35)">'
                          for p in pages)
        d.scene("brand-pages")
        page.set_content(f"""<!doctype html><html><body style="margin:0;background:#1f1f2b;font-family:'Segoe UI',Arial">
            <div style="color:#fff;font:600 26px 'Segoe UI';padding:28px 40px 6px">The branded PDF, page by page</div>
            <div style="display:flex;flex-wrap:wrap;padding:10px 30px">{gallery}</div></body></html>""")
        page.wait_for_timeout(1500)
        d.cap("Cover with a generated image, opening card, text pages, image page, conclusion card and back cover.", 6.0)
        d.scroll(600)
        page.wait_for_timeout(2500)

        # 6. tour
        d.scene("tour")
        for path, text in (("/templates", "Templates: presentation designs built only from the brand's own colours and fonts."),
                           ("/media", "Media Library: approved brand assets, uploads and generated visuals, with licences."),
                           ("/brands", "Brand Manager: the brand profile learned from official references."),
                           ("/settings", "Settings: local AI model, voices, privacy - offline mode is on by default.")):
            d.go(path, 1.0)
            d.cap(text, 3.6)

        # 7. end
        d.scene("end")
        page.set_content(card_html("Zensar Content Studio", "Projects  -  Research Papers  -  Brand Documents<br>Start it with start.bat. Everything runs locally.",
                                   logo, "See docs/User_Manual.pdf to get started"))
        page.wait_for_timeout(6000)
        d.scenes[-1]["end"] = d.now()
        video_path = page.video.path()
        ctx.close()
        browser.close()
    (OUT / "scenes.json").write_text(json.dumps({"video": str(Path(video_path).name), "scenes": d.scenes}, indent=1), encoding="utf-8")
    print("recorded", video_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
