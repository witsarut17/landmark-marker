"""สร้างคู่มือการใช้งานฉบับเต็ม (สำหรับอาจารย์) พร้อมภาพหน้าจอจากเว็บจริงบน GitHub Pages

ปกติใช้ภาพทดสอบสังเคราะห์ (tests/generated/) · ถ้ามีไฟล์จุดของทีมบนแพ็กเกจตัวอย่าง (manual_out/sample_marks.json)
บางขั้นจะใช้ภาพจริงจาก manual_out/sample_package/ (ชุด train) และกำกับหัวข้อว่า (ภาพจริง)
ถ่ายภาพหน้าจออัตโนมัติด้วย Playwright (Edge) ทั้งแบบคอมพิวเตอร์และ iPad (จำลองขนาดจอ)
ฟอนต์ TH Sarabun New (SIPA) ดาวน์โหลดครั้งแรกเก็บไว้ที่ .cache/fonts/
ผล: manual_out/คู่มือการใช้งาน_เว็บมาร์กจุดอ้างอิง.pdf + manual_out/shots/ (อยู่ใน .gitignore)

วิธีใช้:
    python tests/make_test_images.py          # ครั้งแรก (สร้างภาพทดสอบ)
    .venv\\Scripts\\python tools/make_manual.py
    .venv\\Scripts\\python tools/make_manual.py --capture-from http://127.0.0.1:8000/marker/   # ถ่ายจากเว็บในเครื่อง (ก่อน push)
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import math
import re
import shutil
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools"))
from test_coordinates import Input, session, to_page  # noqa: E402
from make_study_package import gitignored  # noqa: E402

SITE = "https://witsarut17.github.io/landmark-marker/"
GEN = ROOT / "tests" / "generated"
OUT = ROOT / "manual_out"
SHOTS = OUT / "shots"
FONT_DIR = ROOT / ".cache" / "fonts"
# TH Sarabun New (SIPA ฟอนต์แห่งชาติ ใช้ได้ฟรี) — ไฟล์ .ttf จาก repo สาธารณะ
FONT_URL = "https://raw.githubusercontent.com/Phonbopit/sarabun-webfont/master/fonts/{}"
FONT_FILES = {"normal": "thsarabunnew-webfont.ttf", "bold": "thsarabunnew_bold-webfont.ttf"}
FONT_FAMILY = "TH Sarabun New"
PDF_NAME = "คู่มือการใช้งาน_เว็บมาร์กจุดอ้างอิง.pdf"
SAMPLE_PKG = OUT / "sample_package"
SAMPLE_KEY = OUT / "sample_key.csv"
SAMPLE_MARKS = OUT / "sample_marks.json"
DESKTOP = {"width": 1366, "height": 768}
IPAD = {"width": 1180, "height": 820}
IPAD_UA = ("Mozilla/5.0 (iPad; CPU OS 26_4 like Mac OS X) AppleWebKit/605.1.15 "
           "(KHTML, like Gecko) Version/26.4 Mobile/15E148 Safari/604.1")
# iPad จริงบน https มีปุ่ม "บันทึกไฟล์สำรองลงแอปไฟล์" — จำลองความสามารถแชร์ไฟล์ให้ปุ่มแสดงในภาพ
IPAD_INIT = """
  Object.defineProperty(navigator, 'platform', { get: () => 'iPad' });
  navigator.canShare = (d) => !!(d && d.files && d.files.length);
  navigator.share = async () => {};
"""

# ---------------------------------------------------------------- วาดเลขวงกลม/กรอบสีแดงบนหน้าเว็บ
ANNOTATE_JS = """
(items) => {
  document.getElementById('__ann')?.remove();
  const layer = document.createElement('div');
  layer.id = '__ann';
  Object.assign(layer.style, { position: 'fixed', left: '0', top: '0', width: '100vw', height: '100vh',
    pointerEvents: 'none', zIndex: '2147483647' });
  const W = window.innerWidth, H = window.innerHeight;
  for (const it of items) {
    if (it.arrow) {            // ลูกศรสีแดงจาก (x1,y1) ไป (x2,y2)
      const a = it.arrow, NS = 'http://www.w3.org/2000/svg';
      const svg = document.createElementNS(NS, 'svg');
      svg.setAttribute('width', W); svg.setAttribute('height', H);
      Object.assign(svg.style, { position: 'absolute', left: '0', top: '0' });
      const ang = Math.atan2(a.y2 - a.y1, a.x2 - a.x1), L = 16, sp = 0.45;
      const hx = a.x2 - L * Math.cos(ang), hy = a.y2 - L * Math.sin(ang);
      const head = `${a.x2},${a.y2} ${a.x2 - L * Math.cos(ang - sp)},${a.y2 - L * Math.sin(ang - sp)} `
                 + `${a.x2 - L * Math.cos(ang + sp)},${a.y2 - L * Math.sin(ang + sp)}`;
      for (const [col, w] of [['rgba(255,255,255,0.9)', 7], ['#e60000', 3]]) {
        const ln = document.createElementNS(NS, 'line');
        Object.entries({ x1: a.x1, y1: a.y1, x2: hx, y2: hy, stroke: col, 'stroke-width': w, 'stroke-linecap': 'round' })
          .forEach(([k, v]) => ln.setAttribute(k, v));
        svg.appendChild(ln);
        const pg = document.createElementNS(NS, 'polygon');
        pg.setAttribute('points', head); pg.setAttribute('fill', '#e60000');
        pg.setAttribute('stroke', col); pg.setAttribute('stroke-width', w === 7 ? 4 : 0);
        svg.appendChild(pg);
      }
      layer.appendChild(svg);
      continue;
    }
    let r = it.rect;
    if (it.sel) {
      const el = document.querySelector(it.sel);
      if (!el || el.offsetParent === null && getComputedStyle(el).position !== 'fixed') continue;
      const b = el.getBoundingClientRect();
      if (!b.width && !b.height) continue;
      r = { x: b.left, y: b.top, w: b.width, h: b.height };
    }
    if (!r) continue;
    const pad = it.pad ?? 3;
    const box = document.createElement('div');
    Object.assign(box.style, { position: 'absolute', left: (r.x - pad) + 'px', top: (r.y - pad) + 'px',
      width: (r.w + 2 * pad) + 'px', height: (r.h + 2 * pad) + 'px', border: `3px ${it.dash ? 'dashed' : 'solid'} #e60000`,
      borderRadius: it.round ? '50%' : '7px', boxSizing: 'border-box', boxShadow: '0 0 0 2px rgba(255,255,255,0.85)' });
    layer.appendChild(box);
    if (it.n != null) {
      const d = 26;
      let cx = r.x - pad - d / 2 + 2, cy = r.y - pad - d / 2 + 2;
      if (it.at === 'below') { cx = r.x + r.w / 2 - d / 2; cy = r.y + r.h + pad + 2; }
      if (it.at === 'right') { cx = r.x + r.w + pad + 2; cy = r.y + r.h / 2 - d / 2; }
      if (it.at === 'left') { cx = r.x - pad - d - 2; cy = r.y + r.h / 2 - d / 2; }
      cx = Math.max(1, Math.min(W - d - 1, cx)); cy = Math.max(1, Math.min(H - d - 1, cy));
      const c = document.createElement('div');
      c.textContent = String(it.n);
      Object.assign(c.style, { position: 'absolute', left: cx + 'px', top: cy + 'px', width: d + 'px', height: d + 'px',
        borderRadius: '50%', background: '#e60000', color: '#fff', font: 'bold 15px/26px Tahoma, sans-serif',
        textAlign: 'center', boxShadow: '0 0 0 2px #fff, 0 1px 4px rgba(0,0,0,0.5)' });
      layer.appendChild(c);
    }
  }
  document.body.appendChild(layer);
}
"""


class Manual:
    """เก็บเนื้อหาตามลำดับ: หัวข้อหลักเลข 1, 2, 3 … ขั้นย่อย 1.1, 1.2 …"""

    def __init__(self):
        self.blocks = []
        self.sec = 1              # หัวข้อ 1 = ภาพรวม (สร้างตอนประกอบเล่ม)
        self.sub = 0
        self.n_shot = 0
        self.titles = ["ภาพรวม"]

    def section(self, title, intro=""):
        self.sec += 1
        self.sub = 0
        self.titles.append(title)
        self.blocks.append(("section", self.sec, title, intro))

    def note(self, text):
        self.blocks.append(("note", text))

    def html(self, text):
        self.blocks.append(("html", text))

    def shot(self, page, title, caption, items=(), device="คอมพิวเตอร์", keep_toast=False):
        """ถ่ายภาพหน้าจอพร้อมเลขกำกับ แล้วเพิ่มเป็น 1 ขั้นย่อย"""
        self.n_shot += 1
        name = f"{self.n_shot:02d}.jpg"
        if not keep_toast:      # ข้อความแจ้งชั่วคราวไม่ต้องอยู่ในภาพ (ยกเว้นขั้นที่อธิบายข้อความนั้น)
            page.evaluate("() => { const t = document.getElementById('toast'); if (t) t.hidden = true; }")
        page.evaluate(ANNOTATE_JS, list(items))
        page.wait_for_timeout(80)
        page.screenshot(path=str(SHOTS / name), type="jpeg", quality=84)
        page.evaluate("() => document.getElementById('__ann')?.remove()")
        self.add_step(title, caption, name, device)
        return name

    def add_step(self, title, caption, img, device):
        self.sub += 1
        self.blocks.append(("step", f"{self.sec}.{self.sub}", title, caption, img, device))


def el(sel, n=None, **kw):
    d = {"sel": sel}
    if n is not None:
        d["n"] = n
    d.update(kw)
    return d


def rect_around(page, which, u, v, r=22, n=None):
    x, y = to_page(page, which, u, v)
    d = {"rect": {"x": x - r, "y": y - r, "w": 2 * r, "h": 2 * r}, "round": True, "pad": 0}
    if n is not None:
        d["n"] = n
    return d


def loupe_item(page, which, n=None):
    lr = page.evaluate("(w) => { const v = window.__marker.viewers[w]; const L = v._loupeRect(); const b = v.canvas.getBoundingClientRect();"
                       " return { x: b.left + L.cx - L.D / 2, y: b.top + L.cy - L.D / 2, w: L.D, h: L.D }; }", which)
    d = {"rect": lr, "round": True, "pad": 4}
    if n is not None:
        d["n"] = n
    return d


def files_of(pkg):
    return [str(p) for p in sorted((GEN / pkg).iterdir()) if p.is_file() and p.name != "targets.json"]


def targets(pkg="test_package"):
    return json.loads((GEN / pkg / "targets.json").read_text(encoding="utf-8"))["targets"]


def open_pkg(page, pkg="test_package"):
    page.set_input_files("#inputFiles", files_of(pkg))
    page.wait_for_function("() => { const v = window.__marker.viewers; return v.xray.img && v.fluoro.img; }", timeout=30000)
    page.wait_for_timeout(300)


def open_pkg_via_home(q, pkg):
    q.click("#btnOpen")
    q.wait_for_selector("#startScreen:not([hidden])")
    open_pkg(q, pkg)


def show(page, i):
    page.evaluate(f"() => {{ window.__marker.showTask({i}); }}")
    page.wait_for_function(f"() => window.__marker.state.index === {i} && window.__marker.state.imagesReady", timeout=30000)
    page.wait_for_timeout(250)


def wait_dialog(page):
    page.wait_for_selector("#dialog:not([hidden])", timeout=8000)
    page.wait_for_timeout(150)


def hold_at(page, inp, which, u, v):
    """กดค้างใกล้เป้า (ยังไม่ปล่อย) คืน (x, y, session)"""
    x, y = to_page(page, which, u, v)
    x, y = x + 9, y - 7
    inp.down(x, y)
    return x, y, session(page, which)


def finish_place(page, inp, which, u, v, x, y, ses):
    x1 = x + (u - ses["x"]) * ses["sL"]
    y1 = y + (v - ses["y"]) * ses["sL"]
    inp.move(x, y, x1, y1)
    page.wait_for_timeout(150)
    return x1, y1


def place(page, inp, which, u, v):
    x, y, ses = hold_at(page, inp, which, u, v)
    x1, y1 = finish_place(page, inp, which, u, v, x, y, ses)
    inp.up(x1, y1)
    page.wait_for_timeout(120)


def choose_reason(page, code, text=None):
    wait_dialog(page)
    page.check(f"#dialog input[value='{code}']")
    if text:
        page.fill("#dialog .text-input", text)
    page.click("#btnReasonOk")


def load_sample_marks(path: Path):
    """อ่านจุดที่ทีมวางบนแพ็กเกจตัวอย่าง: งานปกติ (ต้องครบ 4 คู่) และงาน flip (≥ 1 คู่)"""
    if not SAMPLE_PKG.exists() or not SAMPLE_KEY.exists():
        sys.exit("หยุด: ยังไม่มีแพ็กเกจตัวอย่าง — รัน tools/make_manual_sample.py ก่อน")
    d = json.loads(path.read_text(encoding="utf-8-sig"))
    man = json.loads((SAMPLE_PKG / "manifest.json").read_text(encoding="utf-8"))
    if d.get("package_id") != man["package_id"]:
        sys.exit(f"หยุด: ไฟล์จุด ({d.get('package_id')}) ไม่ใช่ของแพ็กเกจตัวอย่าง ({man['package_id']})")
    import csv as _csv
    rows = list(_csv.DictReader(SAMPLE_KEY.open(encoding="utf-8-sig")))
    flip_id = next((r["task_id"] for r in rows if r["fluo_flag"] == "flip"), None)
    normal_id = next(r["task_id"] for r in rows if r["fluo_flag"] != "flip")

    def pairs(tid):
        t = d["tasks"].get(tid) or {}
        return [((a["x"], a["y"]), (b["x"], b["y"])) for a, b in zip(t.get("xray") or [], t.get("fluoro") or []) if a and b]
    out = {"normal_id": normal_id, "normal": pairs(normal_id), "flip_id": flip_id, "flip": pairs(flip_id) if flip_id else [],
           "index": {it["task_id"]: i for i, it in enumerate(man["items"])}}
    if len(out["normal"]) < 4:
        sys.exit(f"หยุด: งาน {normal_id} ในไฟล์จุดมี {len(out['normal'])} คู่ — ต้องวางครบ 4 คู่")
    return out


def place_visible(page, inp, which, u, v):
    """วางจุดผ่านแว่นขยาย ถ้าจุดอยู่นอกช่องที่มองเห็น ให้ดูทั้งภาพก่อน"""
    x, y = to_page(page, which, u, v)
    b = page.locator("#viewerX" if which == "xray" else "#viewerF").bounding_box()
    if not (b["x"] + 25 < x < b["x"] + b["width"] - 25 and b["y"] + 25 < y < b["y"] + b["height"] - 25):
        page.evaluate(f"() => window.__marker.viewers.{which}.resetView()")
        page.wait_for_timeout(150)
    place(page, inp, which, u, v)


def drag_demo(m: Manual, page, which, R=""):
    """9.1: กดค้างบนจุดที่ใกล้กลางกรอบที่สุด (ภาพแรก + ลูกศรไปแว่นขยาย) แล้วลากไปตำแหน่งใหม่ (ภาพที่สอง)
    คืนพิกัดหน้าจอของจุดหลังย้าย"""
    for _ in range(8):
        r = _drag_plan(page, which)
        if r[0] is not None:
            break
        xs, ys = r[1]                     # ซูมเข้าที่จุด (ยิ่งซูม เมาส์ยิ่งขยับน้อยลง)
        page.mouse.move(xs, ys)
        page.mouse.wheel(0, -180)
        page.wait_for_timeout(200)
    else:
        sys.exit("หยุด: หาทิศทางลากจุดในหัวข้อปรับตำแหน่งไม่ได้")
    (mx, my), (xs, ys), pt = r
    page.mouse.move(xs, ys)
    page.mouse.down()
    page.wait_for_timeout(250)
    lp = loupe_item(page, which, 2)
    L = lp["rect"]
    lx, ly = L["x"] + L["w"] / 2, L["y"] + L["h"] / 2
    d = math.hypot(lx - xs, ly - ys)
    ux, uy = (lx - xs) / d, (ly - ys) / d
    r0, r1 = 24, L["w"] / 2 + 10
    arrow = {"arrow": {"x1": xs + ux * r0, "y1": ys + uy * r0, "x2": lx - ux * r1, "y2": ly - uy * r1}}
    m.shot(page, "ลากจุดเดิมเพื่อปรับตำแหน่ง" + R,
           "ถ้าวางจุดคลาด ไม่ต้องลบแล้ววางใหม่ ให้กดค้างบนจุดนั้น (หมายเลข 1) แว่นขยายจะแสดงที่มุมช่อง (หมายเลข 2) "
           "เพื่อให้เห็นบริเวณใต้นิ้วชัด ๆ",
           [rect_around(page, which, pt["x"], pt["y"], r=18, n=1), lp, arrow])
    page.mouse.move(mx, my, steps=12)
    page.wait_for_timeout(150)
    page.mouse.up()
    page.wait_for_timeout(250)
    new = page.evaluate("([w, i]) => { const q = window.__marker.viewers[w]._points().find(q => q.idx === i);"
                        " return { x: q.x, y: q.y }; }", [which, pt["idx"]])
    nx, ny = to_page(page, which, new["x"], new["y"])
    if math.hypot(nx - xs, ny - ys) < 30:
        sys.exit("หยุด: จุดในหัวข้อปรับตำแหน่งไม่ย้าย")
    old = rect_around(page, which, pt["x"], pt["y"], r=16, n=1)
    old["dash"] = True
    m.shot(page, "ปล่อยแล้วจุดอยู่ที่ตำแหน่งใหม่" + R,
           "เลื่อนช้า ๆ จนตรงตำแหน่งที่ต้องการ แล้วปล่อย จุดจะย้ายจากตำแหน่งเดิม (หมายเลข 1) "
           "ไปอยู่ที่ตำแหน่งใหม่ (หมายเลข 2)",
           [old, rect_around(page, which, new["x"], new["y"], r=16, n=2)])
    return nx, ny


def _drag_plan(page, which):
    """เลือกจุดที่ใกล้กลางกรอบ และทิศทางลากที่จุดใหม่ยังอยู่ในกรอบ ห่างจุดอื่น และเมาส์ไม่ออกนอกจอ
    คืน ((เมาส์ปลายทาง x, y) หรือ None, (จุดบนจอ x, y), จุด)"""
    info = page.evaluate("""(w) => { const v = window.__marker.viewers[w], b = v.canvas.getBoundingClientRect();
        const it = window.__marker.state.manifest.items[window.__marker.state.index], bx = it.box_xyxy;
        return { pts: v._points().map(q => ({ idx: q.idx, x: q.x, y: q.y })), s: v.s, sL: v.loupeScale(),
                 box: w === 'xray' ? bx : [0, 0, v.img.naturalWidth || v.img.width, v.img.naturalHeight || v.img.height],
                 can: { x: b.left, y: b.top, w: b.width, h: b.height } }; }""", which)
    bx = info["box"]
    cu, cv = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
    inside = [q for q in info["pts"] if bx[0] <= q["x"] <= bx[2] and bx[1] <= q["y"] <= bx[3]]
    pt = min(inside or info["pts"], key=lambda q: (q["x"] - cu) ** 2 + (q["y"] - cv) ** 2)
    if not inside:                    # จุดอยู่นอกกรอบ (ภาพทดสอบ) — ไม่บังคับให้ตำแหน่งใหม่อยู่ในกรอบ
        bx = [-1e9, -1e9, 1e9, 1e9]
    xs, ys = to_page(page, which, pt["x"], pt["y"])
    others = [to_page(page, which, q["x"], q["y"]) for q in info["pts"] if q["idx"] != pt["idx"]]
    c = info["can"]
    best = None
    for shift in (60, 48, 38):                    # ระยะที่จุดขยับบนจอ (px)
        for k in range(8):
            ang = math.pi / 4 * k
            nx, ny = xs + shift * math.cos(ang), ys + shift * math.sin(ang)
            mx = xs + (nx - xs) * info["sL"] / info["s"]      # เมาส์ต้องขยับมากกว่าจุด (แว่นขยายช่วยให้ละเอียด)
            my = ys + (ny - ys) * info["sL"] / info["s"]
            u, v = pt["x"] + (nx - xs) / info["s"], pt["y"] + (ny - ys) / info["s"]
            ok = (c["x"] + 40 < nx < c["x"] + c["w"] - 40 and c["y"] + 40 < ny < c["y"] + c["h"] - 40
                  and 5 < mx < DESKTOP["width"] - 5 and 5 < my < DESKTOP["height"] - 5
                  and bx[0] <= u <= bx[2] and bx[1] <= v <= bx[3])
            if ok:
                clear = min([math.hypot(nx - ox, ny - oy) for ox, oy in others] or [999])
                if best is None or clear > best[0]:
                    best = (clear, mx, my)
        if best and best[0] > 45:
            break
    return ((best[1], best[2]) if best else None), (xs, ys), pt


def box_rect(p):
    return p.evaluate("""() => { const v = window.__marker.viewers.xray, it = window.__marker.state.manifest.items[window.__marker.state.index];
      const b = it.box_xyxy, r = v.canvas.getBoundingClientRect(), a = v.imageToScreen(b[0], b[1]), c = v.imageToScreen(b[2], b[3]);
      return { x: r.left + a.x, y: r.top + a.y, w: c.x - a.x, h: c.y - a.y }; }""")


def center_of(p, sel):
    b = p.locator(sel).bounding_box()
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


# ---------------------------------------------------------------- ถ่ายภาพทุกขั้น
def capture(site: str, m: Manual, marks=None, shown: str | None = None):
    shown = shown or site          # ลิงก์ที่พิมพ์ในคู่มือ (ถ่ายภาพจากเว็บในเครื่องได้ แต่คู่มือแสดงลิงก์จริง)
    T = targets()
    with sync_playwright() as pw:
        br = pw.chromium.launch(channel="msedge")

        # ===== 2 เปิดเว็บ =====
        cd = br.new_context(viewport=DESKTOP, device_scale_factor=1.5, accept_downloads=True, bypass_csp=True)
        p = cd.new_page()
        p.goto(site)
        p.wait_for_selector("body[data-ready='1']")
        m.section("เปิดเว็บ และเพิ่มไอคอนบนหน้าจอโฮมของ iPad",
                  f"ลิงก์เว็บคือ {shown} เปิดได้ทั้งบนคอมพิวเตอร์และบน iPad "
                  "บน iPad ให้เปิดเว็บจากไอคอนบนหน้าจอโฮมทุกครั้ง เพราะไอคอนกับ Safari เก็บงานแยกกัน")
        m.shot(p, "เปิดเว็บบนคอมพิวเตอร์",
               "เปิดลิงก์ด้วย Chrome หรือ Edge หมายเลข 1 บอกว่าเครื่องนี้บันทึกงานได้ "
               "และหมายเลข 2 แสดงเมื่อเครื่องนี้ยังไม่มีงานที่บันทึกไว้",
               [el("#storageStatus", 1), el("#noDataBox", 2)])

        ci = br.new_context(viewport=IPAD, device_scale_factor=2, has_touch=True, user_agent=IPAD_UA,
                            accept_downloads=True, bypass_csp=True)
        ci.add_init_script(IPAD_INIT)
        q = ci.new_page()
        q.goto(site)
        q.wait_for_selector("body[data-ready='1']")
        m.shot(q, "เปิดเว็บบน iPad",
               "เปิดลิงก์เว็บด้วย Safari ในแท็บปกติ บน iPad จะมีคำแนะนำการเลือกไฟล์เพิ่มขึ้นที่หมายเลข 1",
               [el("#ipadHint", 1)], device="iPad")
        m.add_step("เพิ่มไอคอนบนหน้าจอโฮม (ภาพจำลอง)",
                   "ใน Safari กดปุ่มแชร์ (หมายเลข 1) กด **เพิ่มไปยังหน้าจอโฮม** (หมายเลข 2) และ **เพิ่ม** "
                   "แล้วไอคอนจะแสดงบนหน้าจอโฮม (หมายเลข 3)",
                   mock_homescreen(br), "iPad ภาพจำลอง")

        # ===== 3 เปิดแพ็กเกจ =====
        m.section("เปิดแพ็กเกจภาพ",
                  "แพ็กเกจภาพคือโฟลเดอร์ที่ทีมวิจัยเตรียมให้ ภายในมีภาพเอกซเรย์และภาพฟลูออโรสโคปีของทุกงาน "
                  "ชื่อไฟล์เป็นรหัสงาน ไม่มีชื่อหรือรหัสผู้ป่วย ทีมวิจัยจะเปิดแพ็กเกจให้แพทย์ในครั้งแรก "
                  "แล้วเว็บจะเก็บภาพไว้ในเครื่อง ครั้งต่อไปแพทย์กด ทำงานต่อ ได้เลยโดยไม่ต้องเลือกไฟล์ "
                  "เมื่อเก็บภาพเสร็จ ทีมวิจัยจะลบโฟลเดอร์แพ็กเกจที่แตกไว้ในแอปไฟล์ และตรวจภาพโดยไปที่งาน 1, 111 และ 222 "
                  "ให้เห็นภาพครบ แล้วกลับไปงาน 1 ก่อนส่งมอบเครื่องให้แพทย์")
        m.shot(p, "เปิดแพ็กเกจบนคอมพิวเตอร์",
               "กด **เลือกทั้งโฟลเดอร์** (หมายเลข 1) แล้วเลือกโฟลเดอร์แพ็กเกจ หากเบราว์เซอร์ถามให้อัปโหลด ให้กด **อัปโหลด** "
               "ภาพจะเปิดในเครื่องนี้เท่านั้น",
               [el("#folderLabel", 1)])
        m.shot(q, "เปิดแพ็กเกจบน iPad",
               "กด **เลือกไฟล์ทั้งหมด** (หมายเลข 1) แล้วกด **เรียกดู** เข้าโฟลเดอร์แพ็กเกจ "
               "จากนั้นกด **เลือก** กด **เลือกทั้งหมด** และกด **เปิด**",
               [el("#filesLabel", 1)], device="iPad")
        # แพ็กเกจทดสอบเล็กมาก เก็บเสร็จเร็วจนถ่ายไม่ทัน จึงแสดงกล่องความคืบหน้าจริงของเว็บค้างไว้ที่ 5 จาก 12 ไฟล์
        n_files = 2 * len(json.loads((GEN / "test_package" / "manifest.json").read_text(encoding="utf-8"))["items"])
        p.evaluate("""(n) => { const b = document.getElementById('importBar'); b.max = n; b.value = 5;
            document.getElementById('importText').textContent = `5/${n} ไฟล์ · 2 MB`;
            document.getElementById('importBox').hidden = false; }""", n_files)
        m.shot(p, "เก็บภาพไว้ในเครื่อง (ครั้งแรกครั้งเดียว)",
               "เมื่อเปิดแพ็กเกจครั้งแรก เว็บจะเก็บภาพไว้ในเครื่องพร้อมแถบความคืบหน้า (หมายเลข 1) "
               "ระหว่างนี้ไม่ควรปิดเว็บหรือสลับแอป",
               [el("#importBox", 1)])
        p.evaluate("() => { document.getElementById('importBox').hidden = true; }")
        open_pkg(p)
        # หน้าที่ต้องเห็นตัวภาพ ใช้ภาพจริงจากแพ็กเกจตัวอย่าง (ถ้ามีไฟล์จุดของทีม) — rp = หน้าเว็บที่เปิดแพ็กเกจตัวอย่าง
        R = " (ภาพจริง)" if marks else ""
        if marks:
            cr = br.new_context(viewport=DESKTOP, device_scale_factor=1.5, bypass_csp=True)
            rp = cr.new_page()
            rp.goto(site)
            rp.wait_for_selector("body[data-ready='1']")
            rp.set_input_files("#inputFiles", [str(f) for f in sorted(SAMPLE_PKG.iterdir()) if f.is_file()])
            rp.wait_for_function("() => { const v = window.__marker.viewers; return v.xray.img && v.fluoro.img; }", timeout=60000)
            show(rp, marks["index"][marks["normal_id"]])
            rinp = Input(rp, cr, "mouse")
        else:
            rp, rinp = p, Input(p, cd, "mouse")
        m.shot(rp, "หน้าจอเมื่อเปิดแพ็กเกจแล้ว" + R,
               "งานแรกจะแสดงทันที ภาพเอกซเรย์อยู่ทางซ้าย (หมายเลข 1) ภาพฟลูออโรสโคปีอยู่ทางขวา (หมายเลข 2) "
               "และแถบหมายเลข 3 บอกขั้นตอนถัดไป",
               [el("#paneX", 1, pad=-2), el("#paneF", 2, pad=-2), el("#hintBar", 3, pad=-2)])

        # ===== 4 หน้าจอหลัก =====
        show(p, 5)
        m.section("หน้าจอหลักและปุ่มต่าง ๆ")
        items = [el("#btnOpen", 1), el("#taskLabel", 2), el("#progress", 3), el(".jump-box", 4, at="below"),
                 el("#btnPrev", 5), el("#btnNext", 6), el("#btnSkip", 7), el("#btnUnmarkable", 8), el("#btnUndo", 9),
                 el("#btnDelete", 10), el("#btnFinger", 11), el("#btnExport", 12), el("#btnFinish", 13),
                 el("#saveLabel", 14, at="below"), el("#btnDebug", 15),
                 el("#hintText", 16, at="below"), el("#pairCount", 17, at="below"), el("#btnNote", 18),
                 el("#howTo", 19, at="below"), el("#btnXView", 20), el("[data-adjust='xray']", 21),
                 el("[data-reset='fluoro']", 22), el("[data-adjust='fluoro']", 23), el("#readoutX", 24, at="below")]
        m.shot(p, "ปุ่มทั้งหมดบนคอมพิวเตอร์", "หมายเลขในภาพตรงกับตารางด้านล่าง", items)
        m.html(BUTTON_TABLE)
        open_pkg(q)
        show(q, 5)
        m.shot(q, "หน้าจอหลักบน iPad",
               "บน iPad แถบด้านบนแบ่งเป็น 2 แถว ปุ่ม **นิ้ววางจุด** (หมายเลข 1) ใช้เมื่อไม่มี Apple Pencil "
               "และหมายเลข 2 บอกวิธีใช้บนเครื่องนั้น",
               [el("#btnFinger", 1), el("#howTo", 2)], device="iPad")

        # ===== 5 ซูม เลื่อน =====
        m.section("ซูม เลื่อนภาพ กลับไปที่กรอบ และดูทั้งภาพ",
                  "การซูมและการเลื่อนภาพเปลี่ยนเฉพาะการแสดงผล ตำแหน่งจุดอ้างอิงไม่เปลี่ยน "
                  "บน iPad ใช้สองนิ้วเพื่อซูมและนิ้วเดียวเพื่อเลื่อนภาพ บนแทร็กแพดของ Mac บีบสองนิ้วเพื่อซูม "
                  "และเลื่อนสองนิ้วเพื่อเลื่อนภาพ")
        m.shot(rp, "ภาพเอกซเรย์ซูมพอดีกรอบ" + R,
               "ภาพเอกซเรย์จะซูมมาที่กรอบเส้นประ (หมายเลข 1) ซึ่งเป็นบริเวณเดียวกับภาพฟลูออโรสโคปี "
               "กด **ดูทั้งภาพ** (หมายเลข 2) เพื่อดูทั้งภาพ",
               [{"rect": box_rect(rp), "n": 1, "pad": 2}, el("#btnXView", 2)])
        rp.click("#btnXView")
        rp.wait_for_timeout(250)
        m.shot(rp, "ดูทั้งภาพ" + R,
               "ภาพเอกซเรย์แสดงทั้งภาพพร้อมกรอบเส้นประ (หมายเลข 1) กด **กลับไปที่กรอบ** (หมายเลข 2) เพื่อซูมกลับไปที่กรอบ",
               [{"rect": box_rect(rp), "n": 1, "pad": 2}, el("#btnXView", 2)])
        rp.click("#btnXView")
        cx, cy = center_of(rp, "#viewerF")
        rp.mouse.move(cx, cy)
        for _ in range(6):
            rp.mouse.wheel(0, -180)
            rp.wait_for_timeout(40)
        rp.wait_for_timeout(250)
        m.shot(rp, "ซูมและเลื่อนภาพ" + R,
               "หมุนล้อเมาส์เพื่อซูม และกดลากเพื่อเลื่อนภาพ ระดับซูมแสดงที่หมายเลข 1 "
               "และกด **รีเซ็ตมุมมอง** (หมายเลข 2) เพื่อกลับขนาดเดิม",
               [el("#readoutF", 1), el("[data-reset='fluoro']", 2)])
        rp.click("[data-reset='fluoro']")
        rp.wait_for_timeout(200)

        # ===== 6 วางจุดคู่ที่ 1 (ภาพจริงถ้ามีไฟล์จุดของทีม) =====
        if marks:
            tx = [a for a, _ in marks["normal"][:4]]
            tf = [b for _, b in marks["normal"][:4]]
        else:
            tx, tf = T["T006_X.png"], T["T006_F.jpg"]
        inp = Input(p, cd, "mouse")
        m.section("วางจุดอ้างอิงคู่ที่ 1",
                  "จุดอ้างอิง 1 คู่ คือตำแหน่งเดียวกันทางกายวิภาคบนภาพเอกซเรย์และบนภาพฟลูออโรสโคปี "
                  "ทุกจุดต้องวางผ่านแว่นขยายเพื่อให้ตำแหน่งแม่นยำ ภาพในหัวข้อนี้ใช้เมาส์บนคอมพิวเตอร์ "
                  "บน iPad ให้แตะด้วย Apple Pencil หรือกดนิ้วค้างเมื่อเปิดปุ่ม **นิ้ววางจุด**")
        m.shot(rp, "ดูว่าต้องวางจุดใด" + R,
               "หมายเลข 1 บอกลำดับจุดที่กำลังวาง และหมายเลข 2 แนะนำให้เลือกจุดที่ชัดและไม่เปลี่ยนรูปตามมุมถ่าย "
               "เช่น ขอบรูกระดูก หรือปลายสกรู",
               [el("#hintChip", 1), el("#hintText", 2)])
        for side, pt in (("xray", tx[0]), ("fluoro", tf[0])):      # ให้จุดแรกอยู่ในช่องที่มองเห็น
            xx, yy = to_page(rp, side, *pt)
            bb = rp.locator("#viewerX" if side == "xray" else "#viewerF").bounding_box()
            if not (bb["x"] + 25 < xx < bb["x"] + bb["width"] - 25 and bb["y"] + 25 < yy < bb["y"] + bb["height"] - 25):
                rp.evaluate(f"() => window.__marker.viewers.{side}.resetView()")
                rp.wait_for_timeout(150)
        x, y, ses = hold_at(rp, rinp, "xray", *tx[0])
        m.shot(rp, "กดค้างบนภาพเอกซเรย์" + R,
               "กดเมาส์ค้างไว้บนภาพเอกซเรย์ (หมายเลข 1) แล้วแว่นขยายจะแสดงที่มุมภาพ (หมายเลข 2)",
               [rect_around(rp, "xray", *tx[0], r=18, n=1), loupe_item(rp, "xray", 2)])
        x1, y1 = finish_place(rp, rinp, "xray", *tx[0], x, y, ses)
        m.shot(rp, "เลื่อนให้กากบาทตรงตำแหน่ง" + R,
               "ยังกดค้างไว้ แล้วเลื่อนช้า ๆ จนกากบาทในแว่นขยาย (หมายเลข 1) ตรงตำแหน่งที่ต้องการ "
               "จุดจะเคลื่อนช้ากว่ามือ จึงวางได้ละเอียด",
               [loupe_item(rp, "xray", 1)])
        rinp.up(x1, y1)
        rp.wait_for_timeout(200)
        m.shot(rp, "ปล่อยเพื่อวางจุดที่ 1 บนภาพเอกซเรย์" + R,
               "ปล่อยเมาส์ จุดที่ 1 จะแสดงบนภาพเอกซเรย์ (หมายเลข 1) และแถบด้านบน (หมายเลข 2) "
               "บอกให้วางจุดที่ 1 บนภาพฟลูออโรสโคปี (หมายเลข 3)",
               [rect_around(rp, "xray", *tx[0], r=16, n=1), el("#hintText", 2), el("#paneF", 3, pad=-3)])
        x, y, ses = hold_at(rp, rinp, "fluoro", *tf[0])
        x1, y1 = finish_place(rp, rinp, "fluoro", *tf[0], x, y, ses)
        m.shot(rp, "วางจุดที่ 1 บนภาพฟลูออโรสโคปี" + R,
               "ใช้วิธีเดียวกัน คือกดค้าง ดูแว่นขยาย (หมายเลข 1) เลื่อนให้ตรงตำแหน่งเดียวกับบนภาพเอกซเรย์ แล้วปล่อย",
               [loupe_item(rp, "fluoro", 1)])
        rinp.up(x1, y1)
        rp.wait_for_timeout(200)
        m.shot(rp, "ได้จุดอ้างอิงคู่ที่ 1" + R,
               "จุดที่ 1 แสดงบนทั้งสองภาพ (หมายเลข 1 และ 2) แถบด้านบนแสดงจำนวนคู่ที่ครบ (หมายเลข 3) "
               "และเปลี่ยนเป็นจุดที่ 2 (หมายเลข 4)",
               [rect_around(rp, "xray", *tx[0], r=16, n=1), rect_around(rp, "fluoro", *tf[0], r=16, n=2),
                el("#pairCount", 3), el("#hintChip", 4)])

        # ===== 7 ครบ 4 คู่ =====
        m.section("วางให้ครบ 4 คู่ และไปงานถัดไป",
                  "จุดทั้ง 4 คู่ควรกระจายทั่วกรอบ หากจุดอยู่ใกล้กันมากหรือเกือบอยู่ในแนวเดียวกัน แถบด้านบนจะแสดงคำเตือน")
        for k in (1, 2, 3):
            place_visible(rp, rinp, "xray", *tx[k])
            place_visible(rp, rinp, "fluoro", *tf[k])
        rp.wait_for_timeout(200)
        m.shot(rp, "วางครบ 4 คู่" + R,
               "จุดทั้ง 4 คู่มีสีต่างกัน (หมายเลข 1) แถบด้านบนแจ้งว่าครบ 4 คู่แล้ว (หมายเลข 2) "
               "จากนั้นกด **ถัดไป** (หมายเลข 3)",
               [el("#paneX", 1, pad=-3), el("#hintText", 2), el("#btnNext", 3)])
        main_full = f"{m.n_shot:02d}.jpg"
        if marks:      # งานสุดท้ายของชุดทดสอบใช้ต่อในขั้น 7.2
            T6x, T6f = T["T006_X.png"], T["T006_F.jpg"]
            for k in range(4):
                place(p, inp, "xray", *T6x[k])
                place(p, inp, "fluoro", *T6f[k])
        p.click("#btnNext")
        wait_dialog(p)
        m.shot(p, "เมื่อถึงงานสุดท้าย",
               "หากยังมีงานที่ไม่เสร็จ ให้กด **ไปงานที่ยังไม่เสร็จ** (หมายเลข 1) "
               "ส่วนงานอื่นที่ไม่ใช่งานสุดท้าย เมื่อกด **ถัดไป** เว็บจะไปงานถัดไปทันที",
               [el("#dialogButtons .btn-primary", 1)])
        p.click("#dialogButtons .btn-primary")
        p.wait_for_function("() => window.__marker.state.index === 0 && window.__marker.state.imagesReady")
        p.wait_for_timeout(250)

        # ===== งานที่ภาพฟลูกลับด้าน (ภาพจริง) =====
        if marks and marks["flip_id"] and marks["flip"]:
            m.section("งานที่ภาพฟลูออโรสโคปีกลับด้าน",
                      "ในบางงาน ภาพฟลูออโรสโคปีกลับด้านซ้ายขวาเมื่อเทียบกับภาพเอกซเรย์ ซึ่งเป็นเรื่องปกติของข้อมูล "
                      "เว็บไม่ได้แจ้งว่างานใดภาพกลับด้าน ทีมวิจัยมีข้อมูลนี้อยู่แล้วและนำไปใช้ตอนคำนวณผล")
            show(rp, marks["index"][marks["flip_id"]])
            for (a, b) in marks["flip"][:4]:
                place_visible(rp, rinp, "xray", *a)
                place_visible(rp, rinp, "fluoro", *b)
            rp.wait_for_timeout(200)
            m.shot(rp, "ตัวอย่างงานที่ภาพฟลูออโรสโคปีกลับด้าน" + R,
                   "ภาพฟลูออโรสโคปี (หมายเลข 1) กลับด้านเมื่อเทียบกับภาพเอกซเรย์ (หมายเลข 2) "
                   "ไม่ต้องแก้ไขภาพ ให้วางจุดตามตำแหน่งที่เห็นบนแต่ละภาพ",
                   [el("#paneF", 1, pad=-3), el("#paneX", 2, pad=-3)])

        # ===== 9 ลาก ย้อน ลบ (ภาพจริง: งานปกติที่วางครบ 4 คู่แล้ว) =====
        t1x, t1f = T["T001_X.png"], T["T001_F.jpg"]
        m.section("ปรับตำแหน่ง ย้อน และลบจุด")
        p.evaluate("() => { window.__marker.viewers.xray.resetView(); window.__marker.viewers.fluoro.resetView(); }")
        p.wait_for_timeout(150)
        if marks:
            show(rp, marks["index"][marks["normal_id"]])
            dp = rp
        else:
            place(p, inp, "xray", *t1x[0])
            place(p, inp, "fluoro", *t1f[0])
            dp = p
        xs, ys = drag_demo(m, dp, "xray", R)
        dp.mouse.click(xs, ys)
        dp.wait_for_timeout(200)
        m.shot(dp, "เลือกจุด แล้วลบหรือย้อน" + R,
               "คลิกจุดเพื่อเลือก (หมายเลข 1) และดูตำแหน่งที่หมายเลข 2 แล้วกด **ลบจุด** (หมายเลข 3) "
               "หรือกด **ย้อน** (หมายเลข 4) เพื่อยกเลิกการทำล่าสุด",
               [{"rect": {"x": xs - 18, "y": ys - 18, "w": 36, "h": 36}, "round": True, "pad": 0, "n": 1},
                el("#readoutX", 2), el("#btnDelete", 3), el("#btnUndo", 4)])

        # ===== 10 3 คู่ / มาร์กไม่ได้ =====
        m.section("กรณีวางได้ 3 คู่ และกรณีมาร์กไม่ได้")
        for k in ((0, 1, 2) if marks else (1, 2)):
            place(p, inp, "xray", *t1x[k])
            place(p, inp, "fluoro", *t1f[k])
        p.click("#btnNext")
        wait_dialog(p)
        m.shot(p, "บันทึกเพียง 3 คู่",
               "หากหาจุดที่ 4 ไม่ได้ ให้กด **ถัดไป** แล้วเลือกเหตุผล (หมายเลข 1) และกด **ยืนยัน** (หมายเลข 2) "
               "หากต้องการกลับไปวางต่อ ให้กด **ยกเลิก**",
               [el("#dialog .reasons", 1), el("#btnReasonOk", 2)])
        choose_reason(p, "no_4th_point")
        p.wait_for_function("() => window.__marker.state.index === 1 && window.__marker.state.imagesReady")
        p.click("#btnUnmarkable")
        wait_dialog(p)
        p.check("#dialog input[value='view_angle']")
        m.shot(p, "มาร์กงานนี้ไม่ได้",
               "กด **มาร์กไม่ได้** แล้วเลือกเหตุผล (หมายเลข 1) และกด **ยืนยัน** (หมายเลข 2) เว็บจะไปงานถัดไป "
               "หากเลือกเหตุผลอื่น ต้องพิมพ์เหตุผลด้วย",
               [el("#dialog .reasons", 1), el("#btnReasonOk", 2)])
        p.click("#btnReasonOk")
        p.wait_for_function("() => window.__marker.state.index === 2 && window.__marker.state.imagesReady")

        # ===== ข้ามไปก่อน / ไปที่งาน =====
        m.section("ข้ามงานไปก่อน และไปที่งาน",
                  "งานที่ข้ามไว้นับว่ายังไม่เสร็จ เว็บจึงมีวิธีกันลืม 3 อย่าง คือแสดงจำนวนงานที่ข้ามไว้ "
                  "พากลับไปงานที่ข้ามเมื่อทำงานอื่นครบ และเตือนเมื่อกดจบงาน")
        p.click("#btnSkip")
        p.wait_for_function("() => window.__marker.state.index === 3 && window.__marker.state.imagesReady")
        p.wait_for_timeout(200)
        m.shot(p, "ข้ามงานที่ยังตัดสินใจไม่ได้",
               "กด **ข้ามไปก่อน** (หมายเลข 1) เว็บจะไปงานถัดไป และแถบด้านบนแสดงจำนวนงานที่ข้ามไว้ (หมายเลข 2)",
               [el("#btnSkip", 1), el("#progress", 2, at="below")])
        p.click("#btnFinish")
        wait_dialog(p)
        m.shot(p, "เตือนเมื่อกดจบงานขณะยังมีงานที่ข้าม",
               "เว็บจะแจ้งจำนวนงานที่ข้ามไว้ กด **ไปทำงานที่ข้ามไว้** (หมายเลข 1) "
               "หรือกด **จบงานไปก่อน** (หมายเลข 2) หากจะหยุดวันนี้",
               [el("#btnFinishGoSkipped", 1), el("#btnFinishAnyway", 2)])
        p.click("#btnFinishCancel")
        p.fill("#jumpInput", "5")
        m.shot(p, "ไปที่งานตามเลขงาน",
               "พิมพ์เลขงานในช่อง **ไปที่งาน** (หมายเลข 1) แล้วกด **ไป** เพื่อกลับไปดูหรือแก้งานเก่า",
               [el(".jump-box", 1, at="below")])
        p.press("#jumpInput", "Enter")
        p.wait_for_function("() => window.__marker.state.index === 4 && window.__marker.state.imagesReady")

        # ===== 10 หมายเหตุ ปรับภาพ =====
        m.section("หมายเหตุและการปรับภาพ")
        p.click("#btnNote")
        wait_dialog(p)
        p.fill("#noteInput", "จุด 3 ไม่แน่ใจ ภาพฟลูเบลอเล็กน้อย")
        m.shot(p, "บันทึกหมายเหตุของงาน",
               "กด **หมายเหตุ** แล้วพิมพ์ข้อความสั้น ๆ (หมายเลข 1) และกด **บันทึก** (หมายเลข 2) "
               "หมายเหตุไม่บังคับ และห้ามใส่ชื่อหรือ HN ผู้ป่วย",
               [el("#noteInput", 1), el("#btnNoteOk", 2)])
        p.click("#btnNoteOk")
        p.wait_for_timeout(200)
        rp.click("[data-adjust='fluoro']")
        rp.check("#adjustF input[data-k='invert']")
        rp.wait_for_timeout(300)
        m.shot(rp, "ปรับความสว่าง ความเปรียบต่าง และกลับสี" + R,
               "กด **ปรับภาพ** (หมายเลข 1) เพื่อปรับความสว่างและความเปรียบต่าง (หมายเลข 2) "
               "หรือกลับสี (หมายเลข 3) ไฟล์ภาพและตำแหน่งจุดไม่เปลี่ยน",
               [el("[data-adjust='fluoro']", 1), el("#adjustF label", 2), el("#adjustF label.check", 3)])
        rp.click("#adjustF [data-adjust-reset]")
        rp.click("#adjustF [data-adjust-close]")
        if marks:
            cr.close()

        # ===== บันทึกอัตโนมัติ / สำรอง =====
        m.section("การบันทึกอัตโนมัติและการสำรองไฟล์",
                  "เว็บบันทึกงานไว้ในเครื่องทุกครั้งที่วางหรือแก้จุด โดยไม่ต้องกดบันทึก และจะให้สำรองเป็นไฟล์ทุกครั้งที่กด "
                  "**จบงาน** หากต้องการสำรองระหว่างทำ กด **ส่งออก** ได้ทุกเมื่อ")
        m.shot(p, "การบันทึกอัตโนมัติ",
               "เวลาที่บันทึกล่าสุดแสดงที่หมายเลข 1 หากมีข้อความว่าบันทึกไม่สำเร็จเป็นสีแดง "
               "ให้กด **ส่งออก** เพื่อสำรองไฟล์ทันที",
               [el("#saveLabel", 1, at="below")])
        p.click("#btnOpen")
        p.wait_for_selector("#startScreen:not([hidden])")
        open_pkg(p, "test_package_big")
        for i in range(10):
            p.click("#btnUnmarkable")
            choose_reason(p, "unclear")
            p.wait_for_function(f"() => window.__marker.state.index === {i + 1} && window.__marker.state.imagesReady")
        p.wait_for_timeout(300)
        # ปิดเว็บโดยไม่กดจบงาน แล้วเปิดใหม่ -> กรอบเตือนงานรอบก่อน
        p2 = cd.new_page()
        p2.goto(site)
        p2.wait_for_selector("#backupReminder:not([hidden])", timeout=10000)
        p2.wait_for_timeout(300)
        m.shot(p2, "เตือนเมื่อครั้งก่อนไม่ได้กดจบงาน",
               "หากครั้งก่อนปิดเว็บโดยไม่กด **จบงาน** หน้าแรกจะเตือนว่ายังไม่ได้สำรอง (หมายเลข 1) "
               "ให้กด **สำรองทันที** (หมายเลข 2)",
               [el("#backupReminder", 1), el("#btnBackupNow", 2)])
        p2.close()
        p.click("#btnExport")
        wait_dialog(p)
        m.shot(p, "สำรองไฟล์ระหว่างทำ",
               "กด **ส่งออก** แล้วกด **ดาวน์โหลดไฟล์สำรอง (JSON)** (หมายเลข 1) ไฟล์จะอยู่ในโฟลเดอร์ Downloads",
               [el("#btnDlJson", 1)])
        with p.expect_download() as dl:
            p.click("#btnDlJson")
        backup = OUT / "_backup_example.json"
        dl.value.save_as(str(backup))
        p.click("#btnExportClose")
        p.wait_for_timeout(300)

        open_pkg_via_home(q, "test_package_big")
        q.click("#btnExport")
        wait_dialog(q)
        m.shot(q, "สำรองไฟล์บน iPad",
               "บน iPad กด **บันทึกไฟล์สำรองลงแอปไฟล์** (หมายเลข 1) แล้วกด **บันทึกไปยังไฟล์** และ **บันทึก** "
               "ไฟล์สำรองจะอยู่ในแอปไฟล์",
               [el("#btnShareJson", 1)], device="iPad")
        q.click("#btnShareJson")
        q.wait_for_timeout(300)

        # ===== 12 จบงาน =====
        m.section("จบงานและส่งไฟล์สำรองให้ทีมวิจัย",
                  "ให้กด **จบงาน** ทุกครั้งก่อนเลิกทำงาน ไฟล์สำรองมีเพียงรหัสงานและตำแหน่งจุดอ้างอิง ไม่มีภาพหรือข้อมูลผู้ป่วย")
        p.click("#btnFinish")
        wait_dialog(p)
        m.shot(p, "จบงานและสำรองไฟล์",
               "กด **จบงาน** แล้วกด **ดาวน์โหลดไฟล์สำรอง (JSON)** (หมายเลข 1) "
               "ไฟล์จะอยู่ในโฟลเดอร์ Downloads ให้ส่งไฟล์ล่าสุดนี้ให้ทีมวิจัย",
               [el("#btnDlJson", 1)])
        with p.expect_download():
            p.click("#btnDlJson")
        p.wait_for_selector("#startScreen:not([hidden])", timeout=8000)
        p.wait_for_timeout(300)
        m.shot(p, "หน้าแรกหลังจบงาน",
               "หน้าแรกจะแสดงจำนวนงานที่ทำแล้ว เวลาที่บันทึกล่าสุด และเวลาที่สำรองไฟล์ล่าสุด (หมายเลข 1)",
               [el("#savedList", 1)])

        # ===== 13 กลับมาทำต่อ / นำเข้า =====
        m.section("กลับมาทำต่อ และการนำเข้าไฟล์สำรอง",
                  "หากหน้าแรกแสดงกรอบสีแดงว่าภาพในเครื่องไม่ครบหรือหายไป ให้ติดต่อทีมวิจัยเพื่อเปิดแพ็กเกจใหม่ "
                  "จุดที่มาร์กไว้ไม่หาย")
        # ภาพแรกของหัวข้อนี้: ถือว่างานรอบก่อนสำรองแล้วทุกแพ็กเกจ (ไม่ให้กรอบเตือนปนในภาพ)
        p.evaluate("""async () => { for (const r of await window.Store.list()) {
            if (r.package_id === '__probe__') continue; r.last_backup_at = new Date().toISOString(); await window.Store.put(r); } }""")
        # ในเครื่องจำลองนี้เปิดมา 2 แพ็กเกจ — เก็บภาพไว้เฉพาะแพ็กเกจล่าสุดเหมือนเครื่องแพทย์จริง
        p.evaluate("""async () => { const l = await window.ImageStore.listRecords();
            l.sort((a, b) => ((a.stored_at || '') < (b.stored_at || '') ? -1 : 1));
            for (const r of l.slice(0, -1)) await window.ImageStore.removePackage(r.package_id); }""")
        p.close()
        p = cd.new_page()
        p.goto(site)
        p.wait_for_selector("body[data-ready='1']")
        p.wait_for_selector("#btnResume")
        p.wait_for_timeout(300)
        m.shot(p, "เปิดเว็บเพื่อทำต่อในวันอื่น",
               "เปิดเว็บด้วยเครื่องและเบราว์เซอร์เดิม หน้าแรกจะแสดงงานที่ทำไว้ (หมายเลข 1) "
               "กด **ทำงานต่อ** (หมายเลข 2) แล้วเว็บจะกลับไปงานล่าสุด",
               [el("#savedList", 1), el("#btnResume", 2)])
        # อัปเดตเว็บเอง: จำลองว่าเซิร์ฟเวอร์มีเวอร์ชันถัดไป แล้วถ่ายข้อความแจ้งก่อนเว็บโหลดใหม่ (0.8 วินาที)
        cur = re.search(r"PELNAV_VERSION = '([^']+)'", (ROOT / "marker" / "version.js").read_text(encoding="utf-8")).group(1)
        nxt = ".".join(cur.split(".")[:2] + [str(int(cur.split(".")[2]) + 1)])
        p.click("#btnResume")
        p.wait_for_function("() => window.__marker.state.imagesReady", timeout=30000)
        p.route("**/version.js?check=*", lambda r: r.fulfill(status=200, content_type="application/javascript",
                                                              body=f"window.PELNAV_VERSION = '{nxt}';"))
        p.evaluate("() => { window.__marker.checkUpdate('manual', true); }")
        p.wait_for_function("() => !document.getElementById('toast').hidden && "
                            "document.getElementById('toast').textContent.includes('มีเวอร์ชันใหม่')", timeout=10000)
        m.shot(p, "เว็บอัปเดตเป็นเวอร์ชันใหม่เอง",
               "เมื่อทีมวิจัยปรับปรุงเว็บ จะมีข้อความแจ้ง (หมายเลข 1) แล้วเว็บโหลดใหม่และกลับเข้างานเดิมเอง "
               "งานที่ทำไว้ไม่หาย และไม่ต้องลบไอคอน",
               [el("#toast", 1)], keep_toast=True)
        p.wait_for_url(f"**?v={nxt}", timeout=15000)
        p.wait_for_selector("body[data-ready='1']")
        p.wait_for_function("() => window.__marker.state.imagesReady", timeout=30000)
        p.unroute("**/version.js?check=*")
        cn = br.new_context(viewport=DESKTOP, device_scale_factor=1.5, bypass_csp=True)
        n = cn.new_page()
        n.goto(site)
        n.wait_for_selector("body[data-ready='1']")
        m.shot(n, "เปลี่ยนเครื่องหรือข้อมูลในเครื่องหาย",
               "หน้าแรกจะแสดงกล่องแจ้งเตือน (หมายเลข 1) ให้กด **นำเข้าไฟล์สำรอง** (หมายเลข 2) แล้วเลือกไฟล์สำรองล่าสุด",
               [el("#noDataBox", 1), el("#noDataBox .file-btn", 2)])
        n.set_input_files("#noDataBox .inputBackup", str(backup))
        wait_dialog(n)
        m.shot(n, "ยืนยันการนำเข้า",
               "เว็บจะสรุปข้อมูลในไฟล์ (หมายเลข 1) แล้วกด **นำเข้า** (หมายเลข 2) หากเครื่องนั้นมีงานอยู่แล้ว "
               "จะให้เลือก **รวม (แนะนำ)** หรือ **แทนที่**",
               [el("#dialogBody", 1), el("#dialogButtons", 2)])
        n.click("#dialogButtons button >> nth=0")
        n.wait_for_timeout(400)
        cn.close()

        # ===== ลบภาพออกจากเครื่อง =====
        m.section("ลบภาพออกจากเครื่องเมื่อทำงานครบ",
                  "เมื่อแพทย์ทำครบทุกงานและส่งไฟล์สำรองให้ทีมวิจัยแล้ว ทีมวิจัยจะลบภาพออกจากเครื่องของแพทย์ให้ "
                  "การลบนี้ลบเฉพาะภาพ ส่วนจุดที่มาร์กไว้ยังอยู่ในเครื่อง จากนั้นทีมวิจัยจะลบโฟลเดอร์แพ็กเกจในแอปไฟล์ "
                  "ล้างรายการ ลบล่าสุด และล้างแคชของแอปที่ใช้ดาวน์โหลดแพ็กเกจ แล้วตรวจว่าพื้นที่ว่างของเครื่องคืนมา")
        p.click("#btnOpen")
        p.wait_for_selector("#btnDeleteImages")
        p.click("#btnDeleteImages")
        wait_dialog(p)
        m.shot(p, "กดลบภาพออกจากเครื่อง",
               "ที่หน้าแรก กด **ลบภาพออกจากเครื่อง** เว็บจะเตือนให้สำรองไฟล์ก่อน (หมายเลข 1) "
               "เมื่อสำรองแล้วให้กด **ลบภาพต่อ** (หมายเลข 2)",
               [el("#btnDelExportFirst", 1), el("#btnDelNext", 2)])
        p.click("#btnDelNext")
        wait_dialog(p)
        m.shot(p, "ยืนยันการลบอีกครั้ง",
               "กด **ลบภาพ** (หมายเลข 1) เพื่อยืนยัน ภาพจะถูกลบออกจากเครื่อง หากกดผิดให้กด **ยกเลิก**",
               [el("#btnDelConfirm", 1)])
        p.click("#btnDelConfirm")
        p.wait_for_function("() => document.getElementById('localBox').hidden", timeout=10000)
        p.wait_for_timeout(300)
        m.shot(p, "หลังลบภาพ",
               "กรอบภาพในเครื่องหายไป ส่วนงานที่ทำไว้ยังแสดงอยู่ (หมายเลข 1) "
               "หากจะทำงานต่อภายหลัง ต้องเปิดแพ็กเกจใหม่",
               [el("#savedList", 1)])

        # ===== 14 สำหรับอาจารย์ =====
        cb = br.new_context(viewport=DESKTOP, device_scale_factor=1.5, bypass_csp=True)
        b = cb.new_page()
        b.goto(site)
        b.wait_for_selector("body[data-ready='1']")
        b.set_input_files("#inputFiles", files_of("bad_size_package"))
        b.wait_for_selector("#errorModal:not([hidden])", timeout=15000)
        m.section("สำหรับอาจารย์: ทดลองใช้เองด้วยชุดภาพทดสอบ", "__TRYOUT__")
        m.shot(b, "เมื่อเปิดแพ็กเกจที่ไม่ถูกต้อง",
               "เว็บจะแสดงหน้าต่าง **หยุด** (หมายเลข 1) และไม่แสดงภาพ เพื่อป้องกันการวางจุดผิดตำแหน่ง",
               [el("#errorModal .card", 1)])
        cb.close()
        br.close()
    return main_full


def mock_homescreen(br) -> str:
    """ภาพจำลอง: ปุ่มแชร์ของ Safari แล้วเพิ่มไปยังหน้าจอโฮม (ใช้ไอคอนจริงของเว็บ)"""
    icon = "data:image/png;base64," + base64.b64encode((ROOT / "marker" / "icon-180.png").read_bytes()).decode()
    page_html = f"""<!doctype html><html lang="th"><head><meta charset="utf-8"><style>
    body {{ margin:0; background:#f2f2f7; font-family:'Leelawadee UI',Tahoma,sans-serif; }}
    .wrap {{ display:flex; gap:28px; padding:26px; align-items:flex-start; }}
    .panel {{ background:#fff; border-radius:14px; box-shadow:0 2px 10px rgba(0,0,0,.15); width:330px; padding:14px; position:relative; }}
    .bar {{ display:flex; align-items:center; gap:10px; background:#e9e9ee; border-radius:10px; padding:8px 10px; font-size:14px; color:#333; }}
    .url {{ flex:1; background:#fff; border-radius:8px; padding:6px 8px; color:#555; font-size:13px; }}
    .share {{ width:30px; height:30px; display:flex; align-items:center; justify-content:center; border-radius:8px; }}
    .menu div {{ padding:11px 12px; border-bottom:1px solid #eee; font-size:15px; }}
    .hl {{ background:#fff1f1; font-weight:bold; }}
    .home {{ background:linear-gradient(160deg,#3a6ea5,#6a4c93); color:#fff; height:260px; display:grid; grid-template-columns:repeat(4,64px);
             gap:18px; padding:20px; border-radius:14px; }}
    .app {{ text-align:center; font-size:11px; }} .app i {{ display:block; width:60px; height:60px; border-radius:14px; background:#fff3; margin:0 auto 4px; }}
    .app img {{ width:60px; height:60px; border-radius:14px; display:block; margin:0 auto 4px; }}
    .n {{ position:absolute; width:28px; height:28px; border-radius:50%; background:#e60000; color:#fff; font:bold 16px/28px Tahoma;
          text-align:center; box-shadow:0 0 0 2px #fff; }}
    .ring {{ position:absolute; border:3px solid #e60000; border-radius:8px; }}
    h4 {{ margin:0 0 10px; font-size:15px; }} .tag {{ font-size:12px; color:#555; }}
    </style></head><body><div class="wrap">
    <div class="panel"><h4>Safari</h4>
      <div class="bar"><span class="url">witsarut17.github.io/landmark-marker/</span>
        <span class="share"><svg width="22" height="26" viewBox="0 0 22 26"><path d="M11 2v14M6 7l5-5 5 5" stroke="#007aff" stroke-width="2.2" fill="none"/><rect x="2" y="10" width="18" height="14" rx="3" stroke="#007aff" stroke-width="2.2" fill="none"/></svg></span></div>
      <div class="ring" style="left:284px;top:46px;width:38px;height:38px"></div><div class="n" style="left:300px;top:24px">1</div>
      <div class="menu" style="margin-top:14px"><div>คัดลอก</div><div>เพิ่มบุ๊กมาร์ก</div><div class="hl">เพิ่มไปยังหน้าจอโฮม</div><div>พิมพ์</div></div>
      <div class="ring" style="left:12px;top:175px;width:306px;height:42px"></div><div class="n" style="left:300px;top:160px">2</div>
      <div class="tag" style="margin-top:10px">ภาพจำลอง ไม่ใช่ภาพหน้าจอจริง ตำแหน่งปุ่มอาจต่างกันตามรุ่นของ iPadOS</div>
    </div>
    <div class="panel" style="width:380px"><h4>หน้าจอโฮมของ iPad</h4>
      <div class="home"><div class="app"><i></i>ไฟล์</div><div class="app"><i></i>Safari</div><div class="app"><i></i>รูปภาพ</div>
        <div class="app"><img src="{icon}">PelNav Marker</div></div>
      <div class="ring" style="left:278px;top:60px;width:76px;height:92px"></div><div class="n" style="left:340px;top:46px">3</div>
    </div></div></body></html>"""
    ctx = br.new_context(viewport={"width": 820, "height": 380}, device_scale_factor=2)
    pg = ctx.new_page()
    pg.set_content(page_html)
    pg.wait_for_timeout(200)
    name = "00_mock_home.jpg"
    pg.screenshot(path=str(SHOTS / name), type="jpeg", quality=88)
    ctx.close()
    return name


# ---------------------------------------------------------------- เนื้อหา
BUTTONS = [
    ("1", "หน้าแรก", "กลับหน้าแรก เพื่อเปิดแพ็กเกจอื่น นำเข้าไฟล์สำรอง หรือดูสถานะงาน"),
    ("2", "T006 / 6", "รหัสงานที่กำลังทำ และจำนวนงานทั้งหมด"),
    ("3", "ทำแล้ว", "จำนวนงานที่ทำเสร็จแล้ว และจำนวนงานที่ข้ามไว้"),
    ("4", "ไปที่งาน", "พิมพ์เลขงานแล้วกดไป เพื่อกลับไปดูหรือแก้งานเก่า"),
    ("5", "ก่อนหน้า", "กลับไปงานก่อนหน้าเพื่อดูหรือแก้ไข"),
    ("6", "ถัดไป", "ไปงานถัดไป เมื่อวางครบ 4 คู่ หรือวาง 3 คู่และระบุเหตุผล"),
    ("7", "ข้ามไปก่อน", "ข้ามงานที่ยังตัดสินใจไม่ได้ เว็บจะพากลับมาเมื่อทำงานอื่นครบ"),
    ("8", "มาร์กไม่ได้", "บันทึกว่างานนี้วางจุดไม่ได้ พร้อมเหตุผล"),
    ("9", "ย้อน", "ยกเลิกการทำล่าสุด"),
    ("10", "ลบจุด", "ลบจุดที่เลือกอยู่"),
    ("11", "นิ้ววางจุด", "ใช้บน iPad ที่ไม่มี Apple Pencil เพื่อวางจุดด้วยการกดนิ้วค้าง"),
    ("12", "ส่งออก", "สำรองไฟล์ผลงานได้ทุกเมื่อ"),
    ("13", "จบงาน", "จบการทำงานรอบนี้ เว็บจะให้สำรองไฟล์ก่อนกลับหน้าแรก"),
    ("14", "บันทึก", "เวลาที่เว็บบันทึกงานในเครื่องครั้งล่าสุด"),
    ("15", "ดีบัก", "ข้อมูลสำหรับทีมวิจัยใช้แก้ปัญหา"),
    ("16", "แถบคำแนะนำ", "บอกขั้นตอนถัดไป และคำเตือนเมื่อจุดอยู่ใกล้กันเกินไป"),
    ("17", "ครบกี่คู่", "จำนวนคู่ที่วางครบทั้งสองภาพแล้ว"),
    ("18", "หมายเหตุ", "บันทึกข้อสังเกตสั้น ๆ ของงานนี้ (ไม่บังคับ)"),
    ("19", "วิธีใช้", "วิธีวางจุด เลื่อน และซูม สำหรับเครื่องที่ใช้อยู่"),
    ("20", "ดูทั้งภาพ", "สลับระหว่างดูภาพเอกซเรย์ทั้งภาพ และกลับไปที่กรอบ"),
    ("21 และ 23", "ปรับภาพ", "ปรับความสว่างและความเปรียบต่าง และกลับสีภาพฟลูออโรสโคปี"),
    ("22", "รีเซ็ตมุมมอง", "ให้ภาพฟลูออโรสโคปีกลับขนาดพอดีกับช่อง"),
    ("24", "ตัวเลขด้านบนภาพ", "ระดับซูม และตำแหน่งของจุดที่เลือก"),
]
BUTTON_TABLE = ('<table class="btns"><tr><th>หมายเลข</th><th>ปุ่มหรือส่วน</th><th>หน้าที่</th></tr>'
                + "".join(f"<tr><td>{a}</td><td>{html.escape(b)}</td><td>{html.escape(c)}</td></tr>" for a, b, c in BUTTONS)
                + "</table>")

OVERVIEW_1 = ("เว็บมาร์กจุดอ้างอิงใช้ให้ศัลยแพทย์วางจุดอ้างอิงที่ตรงกัน 4 คู่ บนภาพเอกซเรย์ก่อนผ่าตัดและภาพฟลูออโรสโคปีระหว่างผ่าตัด "
              "ของผู้ป่วยรายเดียวกันทีละงาน ในชุดทดสอบ 70 ราย จุดอ้างอิงที่ได้ใช้เป็นค่าอ้างอิงในการวัดความแม่นยำของวิธีจัดวางภาพในงานวิจัย "
              "และงานส่วนหนึ่งจะแสดงซ้ำโดยไม่แจ้ง เพื่อใช้วัดความสม่ำเสมอของแพทย์")
OVERVIEW_2 = ("ภาพจะเปิดดูและเก็บไว้ในเครื่องของแพทย์เท่านั้น ไม่ถูกส่งขึ้นอินเทอร์เน็ต และทีมวิจัยจะลบภาพออกจากเครื่องเมื่อทำงานครบ "
              "ภาพทุกภาพปิดชื่อและ HN แล้ว และใช้รหัสงานแทนรหัสผู้ป่วย "
              "ผลที่ได้มีเพียงรหัสงานและตำแหน่งจุดเท่านั้น งานจะบันทึกไว้ในเครื่องโดยอัตโนมัติ และแพทย์ส่งไฟล์สำรองให้ทีมวิจัยเมื่อทำงานเสร็จ")
OVERVIEW_NOTE = ("ภาพหน้าจอทั้งหมดในคู่มือนี้ใช้ภาพทดสอบที่สร้างขึ้น ไม่ใช่ภาพผู้ป่วย "
                 "และเลขในวงกลมสีแดงตรงกับคำอธิบายใต้ภาพ")
OVERVIEW_NOTE_REAL = ("ภาพหน้าจอที่มีคำว่า (ภาพจริง) ในหัวข้อเป็นภาพจริงที่ปิดชื่อและ HN แล้ว "
                      "ภาพหน้าจออื่นใช้ภาพทดสอบที่สร้างขึ้น ไม่ใช่ภาพผู้ป่วย และเลขในวงกลมสีแดงตรงกับคำอธิบายใต้ภาพ")

TRYOUT_INTRO = ("อาจารย์สามารถทดลองใช้เว็บได้เองด้วยชุดภาพทดสอบ ไฟล์ pelnav_testdata.zip ที่ทีมวิจัยส่งให้ "
                "ภาพในชุดนี้สร้างขึ้นเพื่อการทดสอบ ไม่ใช่ภาพผู้ป่วย")
TRYOUT_STEPS = [
    "แตกไฟล์ pelnav_testdata.zip จะได้ 4 โฟลเดอร์ ได้แก่ test_package (6 งาน) test_package_big (12 งาน) "
    "bad_size_package และ bad_exif_package บน iPad ให้บันทึกไฟล์ลงแอปไฟล์ แล้วแตะไฟล์หนึ่งครั้งเพื่อแตกไฟล์",
    "เปิดลิงก์เว็บ แล้วกด **เลือกทั้งโฟลเดอร์** และเลือก test_package บน iPad ให้กด **เลือกไฟล์ทั้งหมด** แทน",
    "ในงาน T001 ถึง T005 ภาพมีกากบาทพร้อมตัวเลขตำแหน่งที่ถูกต้อง เช่น 1 (100,200) ให้วางจุดที่กลางกากบาท "
    "แล้วคลิกที่จุดเพื่อดูตำแหน่งด้านบนภาพ ตำแหน่งควรคลาดไม่เกิน 1 จึงใช้ตรวจความแม่นยำของการวางจุดได้",
    "ในงาน T006 ภาพฟลูออโรสโคปีเป็นบริเวณในกรอบที่ขยาย หมุน และกลับสี ให้ลองวาง 4 คู่ที่กากบาทที่ตรงกันในทั้งสองภาพ",
    "ลองกด **มาร์กไม่ได้** ลองวาง 3 คู่แล้วกด **ถัดไป** ลองบันทึก **หมายเหตุ** และลองกด **ปรับภาพ**",
    "ลองกด **ข้ามไปก่อน** 1 งาน แล้วทำงานที่เหลือให้เสร็จ เว็บต้องพากลับไปงานที่ข้ามเอง "
    "และลองพิมพ์เลขงานในช่อง **ไปที่งาน**",
    "ปิดแท็บระหว่างทำงาน แล้วเปิดลิงก์ใหม่ หน้าแรกต้องแสดงงานที่ทำไว้ และกด **ทำงานต่อ** ได้โดยไม่ต้องเลือกไฟล์ จุดต้องอยู่ครบ",
    "เปิด test_package_big แล้วกด **มาร์กไม่ได้** 3 งาน ปิดแท็บโดยไม่กด **จบงาน** แล้วเปิดลิงก์ใหม่ "
    "หน้าแรกต้องเตือนว่ายังไม่ได้สำรองงานรอบก่อน ให้กด **สำรองทันที** เก็บไฟล์ไว้",
    "เปิดเว็บในเบราว์เซอร์อื่น แล้วกด **นำเข้าไฟล์สำรอง** และเลือกไฟล์จากข้อก่อนหน้า งานต้องกลับมาครบ",
    "เปิด bad_size_package และ bad_exif_package เว็บต้องแสดงหน้าต่าง **หยุด** และไม่แสดงภาพ ดังภาพด้านล่าง",
    "เมื่อทดลองเสร็จ ให้กด **ลบภาพออกจากเครื่อง** ที่หน้าแรก แล้วล้างข้อมูลเว็บไซต์นี้ในเบราว์เซอร์ "
    "หรือลบไอคอนทดสอบบน iPad เพื่อไม่ให้ปนกับงานจริง",
]


def font_css() -> str:
    """ดาวน์โหลด TH Sarabun New ครั้งแรกเก็บไว้ที่ .cache/fonts/ แล้วฝังเป็น @font-face"""
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    css = []
    for weight, fname in FONT_FILES.items():
        f = FONT_DIR / fname
        if not f.exists():
            print(f"ดาวน์โหลดฟอนต์ {fname}")
            with urllib.request.urlopen(FONT_URL.format(fname), timeout=60) as r:
                f.write_bytes(r.read())
        css.append(f"@font-face {{ font-family: '{FONT_FAMILY}'; font-weight: {weight}; src: url('{f.resolve().as_uri()}'); }}")
    return "\n".join(css)


CSS = """
@page { size: A4; margin: 20mm 20mm 20mm 25mm; }
* { box-sizing: border-box; }
body { font-family: 'TH Sarabun New', sans-serif; font-size: 16pt; line-height: 1.35; color: #000; margin: 0; }
b { font-weight: bold; white-space: nowrap; }   /* ชื่อปุ่มไม่ถูกตัดกลางคำ */
h1 { font-size: 30pt; font-weight: bold; margin: 0; line-height: 1.25; }
h2 { font-size: 20pt; font-weight: bold; margin: 0 0 3mm; break-after: avoid; }
h3 { font-size: 17pt; font-weight: bold; margin: 0 0 1.5mm; break-after: avoid; }
p { margin: 0 0 3mm; }
section.sec { break-before: page; padding-top: 3mm; }   /* วรรณยุกต์บนบรรทัดแรกไม่ล้นไปหน้าก่อน */
.step { break-inside: avoid; margin: 0 0 6mm; padding-top: 2mm; }
.step img { width: 100%; max-height: 88mm; object-fit: contain; border: 0.5pt solid #999; display: block; }
.step .cap { margin: 2mm 0 0; }
.step .note { margin: 2mm 0 0; }
.small img { max-height: 75mm; }
.cover { height: 247mm; display: flex; flex-direction: column; justify-content: center; text-align: center; }
.cover p { margin: 6mm 0 0; font-size: 18pt; }
.toc p { margin: 0 0 2mm; }
table.btns { width: 100%; border-collapse: collapse; font-size: 16pt; margin: 0 0 6mm; }
table.btns td, table.btns th { border: 0.5pt solid #999; padding: 1mm 2mm; vertical-align: top; text-align: left; font-weight: normal; }
table.btns th { font-weight: bold; }
table.btns td:first-child { text-align: center; white-space: nowrap; }
ol.try li { margin: 0 0 1mm; padding-top: 1.5mm; break-inside: avoid; }
table.btns tr { break-inside: avoid; }
"""


def rich(text: str) -> str:
    """escape แล้วแปลง **ชื่อปุ่ม** เป็นตัวหนา (ตัวหนาใช้เฉพาะชื่อปุ่มที่ต้องกด)"""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(text, quote=False))


def step_html(st, cls=""):
    _, num, title, cap, img, dev = st
    return (f'<div class="step {cls}"><h3>{num} {html.escape(title)}</h3>'
            f'<img src="shots/{img}">' + (f'<p class="cap">{rich(cap)}</p>' if cap else "") + "</div>")


def build_html(m: Manual, site: str, version: str, main_full: str, real: bool = False) -> str:
    parts = [f'<div class="cover"><h1>คู่มือการใช้งาน<br>เว็บมาร์กจุดอ้างอิง</h1>'
             f"<p>{html.escape(site)}</p><p>เวอร์ชัน {html.escape(version)}</p></div>"]
    parts.append('<section class="sec toc"><h2>สารบัญ</h2>'
                 + "".join(f"<p>{i} {html.escape(t)}</p>" for i, t in enumerate(m.titles, 1)) + "</section>")
    parts.append(f'<section class="sec"><h2>1 ภาพรวม</h2><p>{OVERVIEW_1}</p><p>{OVERVIEW_2}</p>'
                 f'<p>{OVERVIEW_NOTE_REAL if real else OVERVIEW_NOTE}</p>'
                 f'<div class="step small"><h3>1.1 ตัวอย่างหน้าจอเมื่อวางจุดครบ 4 คู่{" (ภาพจริง)" if real else ""}</h3>'
                 f'<img src="shots/{main_full}"></div></section>')
    open_sec = False
    for b in m.blocks:
        if b[0] == "section":
            if open_sec:
                parts.append("</section>")
            intro = b[3]
            if intro == "__TRYOUT__":
                intro_html = (f"<p>{TRYOUT_INTRO}</p><ol class=\"try\">"
                              + "".join(f"<li>{rich(s)}</li>" for s in TRYOUT_STEPS) + "</ol>")
            else:
                intro_html = f"<p>{html.escape(intro)}</p>" if intro else ""
            parts.append(f'<section class="sec"><h2>{b[1]} {html.escape(b[2])}</h2>{intro_html}')
            open_sec = True
        elif b[0] == "html":
            parts.append(b[1])
        elif b[0] == "note":
            note = f'<p class="note">หมายเหตุ: {rich(b[1])}</p>'
            if parts and parts[-1].startswith('<div class="step') and parts[-1].endswith("</div>"):
                parts[-1] = parts[-1][:-len("</div>")] + note + "</div>"     # อยู่ก้อนเดียวกับขั้นก่อนหน้า ไม่แยกหน้า
            else:
                parts.append(note)
        else:
            parts.append(step_html(b, "small" if b[1].startswith(f"{m.sec}.") else ""))
    if open_sec:
        parts.append("</section>")
    return ('<!doctype html><html lang="th"><head><meta charset="utf-8"><title>คู่มือการใช้งาน เว็บมาร์กจุดอ้างอิง</title>'
            f"<style>{font_css()}\n{CSS}</style></head><body>" + "\n".join(parts) + "</body></html>")


def check_text(page_html: str):
    """ตรวจตามข้อกำหนดของคู่มือ: ไม่มีสัญลักษณ์ · — → และไม่มีศัพท์เทคนิคที่ตัดออก"""
    body = re.sub(r"<style>.*?</style>", "", page_html, flags=re.S)
    body = re.sub(r"<[^>]+>", " ", body)
    bad = [s for s in ["·", "—", "→", "HTML", "JavaScript", "connect-src", "EXIF", "analytics", "GitHub", "key.csv",
                       "ภาคผนวก", "คำถามที่พบบ่อย"] if s in body]
    if bad:
        sys.exit(f"หยุด: เนื้อหาคู่มือยังมีคำ/สัญลักษณ์ที่ห้ามใช้ {bad}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", default=SITE, help="ลิงก์เว็บที่พิมพ์ในคู่มือ")
    ap.add_argument("--capture-from", default="",
                    help="ถ่ายภาพหน้าจอจากเว็บนี้แทน (เช่น เว็บในเครื่องก่อน push) — คู่มือยังแสดงลิงก์ --site")
    ap.add_argument("--sample-marks", default=str(SAMPLE_MARKS) if SAMPLE_MARKS.exists() else "",
                    help="ไฟล์สำรอง (.json) ที่ทีมวางจุดบนแพ็กเกจตัวอย่างภาพจริง — ไม่มี = ใช้ภาพทดสอบทั้งเล่ม")
    args = ap.parse_args()
    site = args.site if args.site.endswith("/") else args.site + "/"
    for pkg in ("test_package", "test_package_big", "bad_size_package"):
        if not (GEN / pkg / "manifest.json").exists():
            sys.exit("ยังไม่มีภาพทดสอบ: รัน python tests/make_test_images.py ก่อน")
    if not gitignored(OUT / "x.pdf") or not gitignored(FONT_DIR / "x.ttf"):
        sys.exit("หยุด: manual_out/ และ .cache/ ต้องอยู่ใน .gitignore ก่อน")
    if SHOTS.exists():
        shutil.rmtree(SHOTS)
    SHOTS.mkdir(parents=True)
    marks = load_sample_marks(Path(args.sample_marks)) if args.sample_marks else None

    m = Manual()
    shot_site = args.capture_from or site
    if not shot_site.endswith("/"):
        shot_site += "/"
    main_full = capture(shot_site, m, marks, shown=site)
    version = re.search(r"PELNAV_VERSION = '([^']+)'", (ROOT / "marker" / "version.js").read_text(encoding="utf-8")).group(1)
    page_html = build_html(m, site, version, main_full, bool(marks))
    check_text(page_html)
    src = OUT / "manual.html"
    src.write_text(page_html, encoding="utf-8")
    (OUT / "_backup_example.json").unlink(missing_ok=True)

    pdf = OUT / PDF_NAME
    with sync_playwright() as pw:
        br = pw.chromium.launch(channel="msedge")
        pg = br.new_page()
        pg.goto(src.as_uri())
        pg.wait_for_load_state("networkidle")
        pg.evaluate("() => document.fonts.ready")
        if not pg.evaluate("() => document.fonts.check(\"16pt 'TH Sarabun New'\")"):
            sys.exit("หยุด: โหลดฟอนต์ TH Sarabun New ไม่ได้")
        pg.emulate_media(media="print")
        pg.set_viewport_size({"width": 624, "height": 900})          # กว้างเท่าพื้นที่เนื้อหา A4 (165 มม.)
        long_caps = pg.evaluate("""() => [...document.querySelectorAll('.step')].filter(s => {
            const c = s.querySelector('.cap'); if (!c) return false;
            return Math.round(c.getBoundingClientRect().height / parseFloat(getComputedStyle(c).lineHeight)) > 2;
          }).map(s => s.querySelector('h3').textContent)""")
        if long_caps:
            sys.exit(f"หยุด: คำอธิบายใต้ภาพยาวเกิน 2 บรรทัด {long_caps}")
        pg.pdf(path=str(pdf), format="A4", prefer_css_page_size=True, print_background=True, display_header_footer=False)
        br.close()
    pages = len(re.findall(rb"/Type\s*/Page[^s]", pdf.read_bytes()))
    print(f"ภาพหน้าจอ {m.n_shot} ภาพ, PDF {pages} หน้า, {pdf.stat().st_size / 1e6:.1f} MB")
    print(f"PDF: {pdf}")


if __name__ == "__main__":
    main()
