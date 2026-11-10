"""ทดสอบความถูกต้องของพิกัดและการมาร์กจุดแบบอัตโนมัติในเบราว์เซอร์จริง (Edge ผ่าน Playwright)

ต้องสร้างภาพทดสอบก่อน:  python tests/make_test_images.py
รัน:                     .venv\\Scripts\\python tests/test_coordinates.py      (เพิ่ม --headed เพื่อดูหน้าจอ)

กลุ่มการตรวจ (จอ 3 แบบ: โน้ตบุ๊ก dpr 1, iPad แนวนอน dpr 2, iPad แนวตั้ง dpr 2)
  A  ภาพวาด: กากบาทบนจอตรงกับสูตร (ตรวจพิกเซลบน canvas) คลาด ≤ 0.25 px ภาพ
  L  วางจุดผ่านแว่นขยาย ที่ซูม 1×, 3×, 8× และหลังเลื่อน โดยกดคลาดจากเป้าก่อนแล้วขยับแก้ในแว่น
     ต้องคลาด ≤ 1 px ภาพ ทุกระดับซูม (รวมภาพ 4032 px ที่ซูม 1×) และ image_px_per_screen_px ≤ 0.5
     ใช้เมาส์ (โน้ตบุ๊ก), นิ้วโหมดนิ้ววางจุด และ Apple Pencil จำลอง (iPad)
  B  ท่าทาง: แตะสั้นต้องไม่วางจุดและไม่เลื่อนภาพ, pinch, ลากเลื่อน, ล้อเมาส์
  W  ลำดับการมาร์ก: บังคับคู่ 1→4, วางซ้ำฝั่งเดิมไม่ได้, ลากจุดเดิม, ย้อน, ลบ
  C  ความปลอดภัย: แพ็กเกจผิดขนาด / มี EXIF / ขาดไฟล์ ต้องถูกหยุด และไม่มีคำขอเครือข่ายออกนอกเครื่อง
"""

from __future__ import annotations

import argparse
import functools
import json
import math
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "tests" / "generated"
PRESS_OFFSET = (3.0, -2.0)   # จำลองนิ้ว/เมาส์กดคลาดจากเป้า (CSS px)

RENDER_JS = """
(a) => {
  const v = window.__marker.viewers[a.which];
  v.render();
  const c = v.canvas, ctx = c.getContext('2d');
  const k = c.width / v.cssW;
  const q = v.imageToScreen(a.u, a.v);
  function centroid(data) {
    let sw = 0, sx = 0;
    for (let i = 0; i < data.length / 4; i++) {
      const lum = (data[4*i] + data[4*i+1] + data[4*i+2]) / 3;
      const w = Math.max(0, lum - 160);
      sw += w; sx += w * (i + 0.5);
    }
    return sw > 0 ? sx / sw : null;
  }
  const half = Math.max(4, 4 * v.s);
  const yRow = Math.floor((v.ty + (a.v - 12) * v.s) * k);
  const x0 = Math.floor((q.x - half) * k), x1 = Math.ceil((q.x + half) * k);
  const xc = centroid(ctx.getImageData(x0, yRow, x1 - x0, 1).data);
  const xCol = Math.floor((v.tx + (a.u - 12) * v.s) * k);
  const y0 = Math.floor((q.y - half) * k), y1 = Math.ceil((q.y + half) * k);
  const yc = centroid(ctx.getImageData(xCol, y0, 1, y1 - y0).data);
  if (xc == null || yc == null) return null;
  return { dx: ((x0 + xc) / k - q.x) / v.s, dy: ((y0 + yc) / k - q.y) / v.s };
}
"""


# ตรวจว่าภาพในแว่นขยายวางตรงกับตำแหน่งจุดที่จะบันทึก (กากบาทของภาพทดสอบต้องอยู่ตรงที่สูตรบอก)
LOUPE_JS = """
(a) => {
  const v = window.__marker.viewers[a.which];
  const ses = v.session;
  if (!ses) return null;
  v._testHideLoupeCross = true; v.render();
  const c = v.canvas, ctx = c.getContext('2d');
  const k = c.width / v.cssW;
  const { cx, cy, D } = v._loupeRect();
  const sL = ses.sL;
  const off = Math.min(12, Math.max(5, 0.3 * D / sL));   // ระยะจากกลางกากบาทที่ใช้วัด (px ภาพ) ให้อยู่ในแว่น
  const ex = cx + (a.u - ses.point.x) * sL, ey = cy + (a.v - ses.point.y) * sL;
  function centroid(data) {
    let sw = 0, sx = 0;
    for (let i = 0; i < data.length / 4; i++) {
      const lum = (data[4*i] + data[4*i+1] + data[4*i+2]) / 3;
      const w = Math.max(0, lum - 160);
      sw += w; sx += w * (i + 0.5);
    }
    return sw > 0 ? sx / sw : null;
  }
  const half = Math.min(4 * sL, 0.25 * D);
  const yRow = Math.floor((ey - off * sL) * k);
  const x0 = Math.floor((ex - half) * k), x1 = Math.ceil((ex + half) * k);
  const xc = centroid(ctx.getImageData(x0, yRow, x1 - x0, 1).data);
  const xCol = Math.floor((ex - off * sL) * k);
  const y0 = Math.floor((ey - half) * k), y1 = Math.ceil((ey + half) * k);
  const yc = centroid(ctx.getImageData(xCol, y0, 1, y1 - y0).data);
  v._testHideLoupeCross = false; v.render();
  if (xc == null || yc == null) return null;
  return { dx: ((x0 + xc) / k - ex) / sL, dy: ((y0 + yc) / k - ey) / sL,
           centerErr: Math.hypot(ex - cx, ey - cy) / sL };
}
"""


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def start_server():
    handler = functools.partial(Quiet, directory=str(ROOT))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


class Results:
    def __init__(self):
        self.rows, self.fails = [], []
        self.places = []   # (s, คลาด px ภาพ, ipp, ชื่อ)

    def check(self, ok: bool, label: str, detail: str = ""):
        self.rows.append((ok, label, detail))
        if not ok:
            self.fails.append(f"{label} {detail}")


def package_files(name: str, skip: str | None = None):
    d = GEN / name
    return [str(p) for p in sorted(d.iterdir()) if p.is_file() and p.name != "targets.json" and p.name != skip]


def open_package(page, base, files, goto=True):
    if goto:
        page.goto(f"{base}/marker/index.html")
    page.wait_for_selector("body[data-ready='1']")
    page.set_input_files("#inputFiles", files)


def wait_loaded(page):
    page.wait_for_function("() => { const v = window.__marker.viewers; return v.xray.img && v.fluoro.img; }")


def canvas_box(page, which):
    return page.evaluate(
        "(w) => { const r = window.__marker.viewers[w].canvas.getBoundingClientRect(); return {x: r.left, y: r.top, w: r.width, h: r.height}; }",
        which)


def view(page, which):
    return page.evaluate(
        "(w) => { const v = window.__marker.viewers[w]; return {s: v.s, tx: v.tx, ty: v.ty, fit: v.fitScale, W: v.W, H: v.H, cssW: v.cssW, cssH: v.cssH}; }",
        which)


def marks(page):
    return page.evaluate("() => window.__marker.marks()")


def session(page, which):
    return page.evaluate(
        "(w) => { const s = window.__marker.viewers[w].session; return s && {x: s.point.x, y: s.point.y, sL: s.sL, idx: s.idx, mode: s.mode}; }",
        which)


def to_page(page, which, u, v):
    vw, box = view(page, which), canvas_box(page, which)
    return box["x"] + vw["tx"] + u * vw["s"], box["y"] + vw["ty"] + v * vw["s"]


class Input:
    """เมาส์ / นิ้ว / ปากกา ผ่าน Playwright + CDP"""

    def __init__(self, page, ctx, kind):
        self.page, self.kind = page, kind
        self.cdp = ctx.new_cdp_session(page)
        self.cfg = page.evaluate("() => window.MARKER_CONFIG.input")

    def _touch(self, typ, pts):
        self.cdp.send("Input.dispatchTouchEvent", {"type": typ, "touchPoints": pts})

    def _pen(self, typ, x, y):
        self.cdp.send("Input.dispatchMouseEvent", {
            "type": typ, "x": x, "y": y, "button": "left", "buttons": 0 if typ == "mouseReleased" else 1,
            "clickCount": 1, "pointerType": "pen", "force": 0.5})

    def down(self, x, y, hold=True):
        if self.kind == "mouse":
            self.page.mouse.move(x, y)
            self.page.mouse.down()
            if hold:
                self.page.wait_for_timeout(self.cfg["mouseHoldMs"] + 120)
        elif self.kind == "touch":
            self._touch("touchStart", [{"x": x, "y": y, "id": 1}])
            if hold:
                self.page.wait_for_timeout(self.cfg["touchHoldPlaceMs"] + 120)
        else:
            self._pen("mousePressed", x, y)

    def move(self, x0, y0, x1, y1, steps=6):
        for k in range(1, steps + 1):
            x, y = x0 + (x1 - x0) * k / steps, y0 + (y1 - y0) * k / steps
            if self.kind == "mouse":
                self.page.mouse.move(x, y)
            elif self.kind == "touch":
                self._touch("touchMove", [{"x": x, "y": y, "id": 1}])
            else:
                self._pen("mouseMoved", x, y)

    def up(self, x, y):
        if self.kind == "mouse":
            self.page.mouse.up()
        elif self.kind == "touch":
            self._touch("touchEnd", [])
        else:
            self._pen("mouseReleased", x, y)
        self.page.wait_for_timeout(20)

    def tap(self, x, y):
        self.down(x, y, hold=False)
        self.up(x, y)


def place(page, inp: Input, which, u, v, offset=PRESS_OFFSET, loupe_check=None):
    """กดใกล้เป้า (คลาด offset) -> แว่นขยายขึ้น -> ขยับแก้ให้ตรงเป้า -> ปล่อย  คืนค่าข้อมูล session"""
    x, y = to_page(page, which, u, v)
    x, y = x + offset[0], y + offset[1]
    inp.down(x, y)
    ses = session(page, which)
    if not ses:
        inp.up(x, y)
        return None
    x1 = x + (u - ses["x"]) * ses["sL"]
    y1 = y + (v - ses["y"]) * ses["sL"]
    inp.move(x, y, x1, y1)
    # เบราว์เซอร์ประมวลผลการขยับตามรอบเฟรม -> รอให้จุดตามมาถึงก่อนตรวจ
    try:
        page.wait_for_function(
            "(a) => { const s = window.__marker.viewers[a.w].session;"
            " return s && Math.abs(s.point.x - a.u) < 0.2 && Math.abs(s.point.y - a.v) < 0.2; }",
            arg={"w": which, "u": u, "v": v}, timeout=1000)
    except Exception:
        pass
    if loupe_check is not None:
        loupe_check.append(page.evaluate(LOUPE_JS, {"which": which, "u": u, "v": v}))
    inp.up(x1, y1)
    return ses


def render_check(page, res, which, u, v, label):
    vw = view(page, which)
    if vw["s"] < 2:
        return
    r = page.evaluate(RENDER_JS, {"which": which, "u": u, "v": v})
    ok = r is not None and abs(r["dx"]) <= 0.25 and abs(r["dy"]) <= 0.25
    res.check(ok, f"A ภาพวาด {label}", f"dx={r['dx']:.3f} dy={r['dy']:.3f} px ภาพ" if r else "หาเส้นไม่เจอ")


def place_check(page, res, inp, which, u, v, label):
    vw = view(page, which)
    qx, qy = vw["tx"] + u * vw["s"], vw["ty"] + v * vw["s"]
    if not (10 < qx < vw["cssW"] - 10 and 10 < qy < vw["cssH"] - 10):
        return
    page.evaluate("() => window.__marker.clearMarks()")
    render_check(page, res, which, u, v, label)
    lc = []
    ses = place(page, inp, which, u, v, loupe_check=lc)
    r = lc[0] if lc else None
    res.check(r is not None and abs(r["dx"]) <= 0.25 and abs(r["dy"]) <= 0.25 and r["centerErr"] <= 0.25,
              f"A แว่นขยาย {label}",
              f"ภาพในแว่นเยื้อง dx={r['dx']:.3f} dy={r['dy']:.3f} · เป้าห่างกลางแว่น {r['centerErr']:.3f} px ภาพ" if r else "หาเส้นในแว่นไม่เจอ")
    m = marks(page)
    p = m and m[which][0]
    if not ses or not p:
        res.check(False, f"L วางจุด {label}", "แว่นขยายไม่ขึ้น/ไม่ได้จุด")
        return
    err = math.hypot(p["x"] - u, p["y"] - v)
    ipp = p["image_px_per_screen_px"]
    res.places.append((vw["s"], err, ipp, label))
    ok = err <= 1.0 and ipp <= 0.5 and abs(ipp - 1 / ses["sL"]) < 1e-3
    res.check(ok, f"L วางจุด {label}",
              f"ได้ ({p['x']}, {p['y']}) ควร ({u}, {v}) คลาด {err:.3f} px ภาพ · ipp {ipp} · แว่น×{ses['sL']:.1f}")


def set_zoom(page, which, zoom, anchor_u, anchor_v, at_fx=0.5, at_fy=0.5):
    page.evaluate("""(a) => {
        const v = window.__marker.viewers[a.which];
        v.resetView();
        const s = v.fitScale * a.zoom;
        v.setView(s, v.cssW * a.fx - a.u * s, v.cssH * a.fy - a.v * s);
    }""", {"which": which, "zoom": zoom, "u": anchor_u, "v": anchor_v, "fx": at_fx, "fy": at_fy})


def goto_task(page, i):
    page.evaluate(f"() => window.__marker.showTask({i})")
    page.wait_for_function(
        f"() => window.__marker.state.index === {i} && window.__marker.viewers.xray.img && window.__marker.viewers.fluoro.img")


def gesture_tests(page, ctx, res, name, touch, targets, manifest):
    goto_task(page, 0)
    page.evaluate("() => window.__marker.clearMarks()")
    which, fname = "xray", manifest["items"][0]["xray"]
    u, v = targets[fname][0]
    page.evaluate("() => window.__marker.viewers.xray.resetView()")
    vw, box = view(page, which), canvas_box(page, which)
    px, py = to_page(page, which, u, v)
    inp = Input(page, ctx, "touch" if touch else "mouse")

    # แตะสั้น: ต้องไม่วางจุด ไม่เลื่อนภาพ
    inp.tap(px, py)
    m, after = marks(page), view(page, which)
    res.check(not any(m["xray"]) and abs(after["tx"] - vw["tx"]) < 1e-6, f"B แตะสั้นไม่วางจุด [{name}]",
              f"จุด {m['xray']} · tx {vw['tx']:.2f}->{after['tx']:.2f}")

    if touch:
        # โหมดนิ้ววางจุดปิด: กดค้างต้องไม่วางจุด
        page.evaluate("() => window.__marker.setFingerMode(false)")
        inp.down(px, py)
        ses = session(page, which)
        inp.up(px, py)
        res.check(ses is None and not any(marks(page)["xray"]), f"B นิ้วกดค้างตอนปิดโหมด ไม่วางจุด [{name}]", f"session={ses}")
        page.evaluate("() => window.__marker.setFingerMode(true)")

        # pinch รอบกลางช่อง (นิ้วต้องอยู่ในช่องตลอด ถ้าออกนอกหน้าต่าง เบราว์เซอร์อาจไม่ส่งเหตุการณ์ของนิ้วนั้น)
        # ใช้จำนวนเต็ม: เบราว์เซอร์ปัดพิกัดนิ้วจำลองเป็นจำนวนเต็ม (ต่าง 0.5 px ตอนเริ่ม × ซูม 8 เท่า = เลื่อน ~4 px)
        qx, qy = round(box["x"] + box["w"] / 2), round(box["y"] + box["h"] / 2)
        spread = min(160, box["w"] / 2 - 10)

        def tp(dx):
            return [{"x": qx - dx, "y": qy, "id": 1}, {"x": qx + dx, "y": qy, "id": 2}]
        before = page.evaluate(f"() => window.__marker.viewers.xray.screenToImage({qx - box['x']}, {qy - box['y']})")
        inp._touch("touchStart", tp(20))
        for dx in range(25, int(spread) + 1, 5):
            inp._touch("touchMove", tp(dx))
        inp._touch("touchEnd", [])
        after = view(page, which)
        still = page.evaluate(f"() => window.__marker.viewers.xray.screenToImage({qx - box['x']}, {qy - box['y']})")
        drift = math.hypot(still["x"] - before["x"], still["y"] - before["y"]) * after["s"]
        res.check(after["s"] > vw["s"] * 3 and drift < 1.0 and not any(marks(page)["xray"]), f"B pinch [{name}]",
                  f"ซูม {vw['s']:.3f} -> {after['s']:.3f}, จุดใต้นิ้วเลื่อน {drift:.2f} px จอ")
        cx, cy = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
        inp._touch("touchStart", [{"x": cx, "y": cy, "id": 1}])
        for k in range(1, 11):
            inp._touch("touchMove", [{"x": cx + 6 * k, "y": cy - 4 * k, "id": 1}])
        inp._touch("touchEnd", [])
        moved = view(page, which)
        res.check(abs(moved["tx"] - after["tx"] - 60) < 0.5 and abs(moved["ty"] - after["ty"] + 40) < 0.5
                  and not any(marks(page)["xray"]),
                  f"B ลากนิ้วเลื่อน [{name}]", f"เลื่อน ({moved['tx'] - after['tx']:.2f}, {moved['ty'] - after['ty']:.2f}) ควร (60, -40)")
    else:
        page.mouse.move(px, py)
        for _ in range(6):
            page.mouse.wheel(0, -200)
        page.wait_for_timeout(50)
        z = view(page, which)
        cx, cy = box["x"] + box["w"] * 0.5, box["y"] + box["h"] * 0.5
        page.mouse.move(cx, cy)
        page.mouse.down()
        for k in range(1, 11):
            page.mouse.move(cx - 7 * k, cy + 5 * k)
        page.mouse.up()
        moved = view(page, which)
        res.check(moved["s"] > vw["s"] * 2 and abs(moved["tx"] - z["tx"] + 70) < 0.5 and abs(moved["ty"] - z["ty"] - 50) < 0.5
                  and not any(marks(page)["xray"]),
                  f"B ล้อเมาส์+ลาก [{name}]", f"ซูม {vw['s']:.3f}->{moved['s']:.3f}, เลื่อน ({moved['tx'] - z['tx']:.1f}, {moved['ty'] - z['ty']:.1f}) ควร (-70, 50)")
    for (u2, v2) in targets[fname]:
        place_check(page, res, inp, which, u2, v2, f"[{name}] {fname} ({u2},{v2}) หลังซูม/เลื่อนด้วยมือ")


def workflow_tests(page, ctx, res, name, targets, manifest):
    goto_task(page, 0)
    page.evaluate("() => window.__marker.clearMarks()")
    page.evaluate("() => { window.__marker.viewers.xray.resetView(); window.__marker.viewers.fluoro.resetView(); }")
    inp = Input(page, ctx, "mouse")
    it = manifest["items"][0]
    tx_, tf = targets[it["xray"]], targets[it["fluoro"]]

    place(page, inp, "xray", *tx_[0])
    m = marks(page)
    res.check(m["xray"][0] is not None, f"W วางจุด 1 เอกซเรย์ [{name}]", str(m["xray"][0]))

    # วางซ้ำบนเอกซเรย์ต้องไม่ได้ (ต้องไปวางจุด 1 บนฟลูก่อน)
    x, y = to_page(page, "xray", *tx_[1])
    inp.down(x, y)
    ses = session(page, "xray")
    inp.up(x, y)
    m = marks(page)
    toast = page.text_content("#toast") or ""
    res.check(ses is None and m["xray"][1] is None and "ฟลู" in toast, f"W บังคับลำดับคู่ [{name}]", f"session={ses} toast='{toast}'")

    place(page, inp, "fluoro", *tf[0])
    place(page, inp, "xray", *tx_[1])
    m = marks(page)
    res.check(m["fluoro"][0] is not None and m["xray"][1] is not None, f"W จุด 1 ฟลู แล้วจุด 2 เอกซเรย์ [{name}]",
              f"fluoro[0]={m['fluoro'][0]} xray[1]={m['xray'][1]}")

    # ลากจุดเดิม: เมาส์กดบนจุด 2 แล้วลาก (40, 20) px จอ
    old = m["xray"][1]
    x, y = to_page(page, "xray", old["x"], old["y"])
    inp.down(x, y, hold=False)
    ses = session(page, "xray")
    inp.move(x, y, x + 40, y + 20)
    inp.up(x + 40, y + 20)
    new = marks(page)["xray"][1]
    ok = ses is not None and ses["mode"] == "move" and \
        abs(new["x"] - (old["x"] + 40 / ses["sL"])) <= 0.06 and abs(new["y"] - (old["y"] + 20 / ses["sL"])) <= 0.06
    res.check(ok, f"W ลากจุดเดิม [{name}]", f"{old} -> {new}")

    page.evaluate("() => window.__marker.undo()")
    back = marks(page)["xray"][1]
    res.check(back["x"] == old["x"] and back["y"] == old["y"], f"W ย้อน [{name}]", f"{back}")

    # เลือกจุด 1 (คลิกสั้นบนจุด) แล้วลบ -> ต้องกลับไปรอจุด 1 บนเอกซเรย์
    p1 = marks(page)["xray"][0]
    x, y = to_page(page, "xray", p1["x"], p1["y"])
    page.mouse.click(x, y)
    page.evaluate("() => window.__marker.deleteSelected()")
    m = marks(page)
    hint = page.text_content("#hintText") or ""
    res.check(m["xray"][0] is None and m["xray"][1] is not None and "จุด 1" in hint and "เอกซเรย์" in hint,
              f"W ลบจุด [{name}]", f"xray={m['xray'][:2]} hint='{hint}'")
    page.evaluate("() => window.__marker.undo()")
    res.check(marks(page)["xray"][0] is not None, f"W ย้อนการลบ [{name}]", "")

    # ครบ 4 คู่แล้ววางเพิ่มไม่ได้
    page.evaluate("() => window.__marker.clearMarks()")
    for k in range(4):
        place(page, inp, "xray", *tx_[k])
        place(page, inp, "fluoro", *tf[k])
    m = marks(page)
    full = all(m["xray"]) and all(m["fluoro"])
    x, y = to_page(page, "fluoro", *tf[4])
    inp.down(x, y)
    ses = session(page, "fluoro")
    inp.up(x, y)
    hint = page.text_content("#hintText") or ""
    res.check(full and ses is None and "ครบ 4 คู่" in hint, f"W ครบ 4 คู่ [{name}]", f"hint='{hint}' session={ses}")


# เก็บ error ทุกชนิดในหน้า (รวม "ResizeObserver loop ...") ตั้งแต่ก่อนโหลดหน้า
ERR_INIT = "window.__errs = []; window.addEventListener('error', e => window.__errs.push(String(e.message)));"


def new_page(pw_browser, vp, dpr, touch=False):
    ctx = pw_browser.new_context(viewport=vp, device_scale_factor=dpr, has_touch=touch, is_mobile=False)
    ctx.add_init_script(ERR_INIT)
    return ctx, ctx.new_page()


def check_no_ro_errors(page, res, label):
    errs = page.evaluate("() => window.__errs || []")
    ro = [e for e in errs if "ResizeObserver" in e]
    res.check(not errs, f"R ไม่มี error ในหน้า (รวม ResizeObserver) {label}",
              f"ResizeObserver {len(ro)} ครั้ง · error ทั้งหมด {len(errs)}: {errs[:3]}")


def set_scale(page, which, s, u, v):
    """ซูมแบบกำหนดสเกลตรง ๆ (px จอ ต่อ px ภาพ) ให้เป้าอยู่กลางช่อง"""
    page.evaluate("""(a) => { const q = window.__marker.viewers[a.w];
        q.resetView(); q.setView(a.s, q.cssW / 2 - a.u * a.s, q.cssH / 2 - a.v * a.s); }""",
                  {"w": which, "s": s, "u": u, "v": v})


def sequence_tests(pw_browser, base, res: Results, name, vp, dpr, pkg):
    """ลำดับจริง: เปิดแพ็กเกจใหม่ -> วางบนงานแรกทันที (ไม่กดไปงานอื่นก่อน) ทั้ง ฟลู→เอกซเรย์ และ เอกซเรย์→ฟลู
    จุด 1 ที่ซูม 1× · จุด 2 ซูมเข้า (8 px จอ/px ภาพ) · แล้วกด ถัดไป และกลับมา T001 วางจุด 3 ต่อได้"""
    manifest = json.loads((GEN / pkg / "manifest.json").read_text(encoding="utf-8"))
    targets = json.loads((GEN / pkg / "targets.json").read_text(encoding="utf-8"))["targets"]
    it = manifest["items"][0]
    tgt = {"xray": targets[it["xray"]], "fluoro": targets[it["fluoro"]]}
    first = f"{it['task_id']}: X {it['xray_size'][0]}×{it['xray_size'][1]}"
    for order in (("fluoro", "xray"), ("xray", "fluoro")):
        tag = f"[{name}] {pkg} ({first}) {'ฟลู→เอกซเรย์' if order[0] == 'fluoro' else 'เอกซเรย์→ฟลู'}"
        ctx, page = new_page(pw_browser, vp, dpr)
        open_package(page, base, package_files(pkg))
        wait_loaded(page)
        inp = Input(page, ctx, "mouse")

        def put(k, side, mode):
            u, v = tgt[side][k]
            if mode == "1×":
                page.evaluate(f"() => window.__marker.viewers['{side}'].resetView()")
            else:
                set_scale(page, side, 8, u, v)
            place(page, inp, side, u, v)
            p = marks(page)[side][k]
            err = math.hypot(p["x"] - u, p["y"] - v) if p else None
            res.check(p is not None and err <= 1.0, f"S {tag} จุด {k + 1} {SIDE_TH[side]} ซูม {mode}",
                      f"ได้ {p} ควร ({u}, {v})" + (f" คลาด {err:.2f}" if p else " — วางไม่ได้!"))

        for side in order:
            put(0, side, "1×")
        for side in order:
            put(1, side, "เข้า")
        goto_task(page, 1)
        goto_task(page, 0)
        m = marks(page)
        res.check(all(m[s][k] for s in ("xray", "fluoro") for k in (0, 1)), f"S {tag} กลับมา T001 จุดเดิมยังอยู่", str(m))
        for side in order:
            put(2, side, "1×")
        check_no_ro_errors(page, res, tag)
        ctx.close()


SIDE_TH = {"xray": "เอกซเรย์", "fluoro": "ฟลู"}


def robustness_tests(pw_browser, base, res: Results, name, vp, dpr):
    """ซูมสูงสุดต้องไม่เกิน 10 px จอ/px ภาพ · ช่องเปลี่ยนขนาดระหว่างวางจุด ต้องไม่ยกเลิกและจุดไม่กระโดด"""
    ctx, page = new_page(pw_browser, vp, dpr)
    open_package(page, base, package_files("test_package"))
    wait_loaded(page)
    inp = Input(page, ctx, "mouse")
    x, y = to_page(page, "xray", 100, 200)
    page.mouse.move(x, y)
    for _ in range(80):
        page.mouse.wheel(0, -400)
    page.wait_for_timeout(100)
    s = page.evaluate("() => [window.__marker.viewers.xray.s, window.__marker.viewers.xray.loupeScale()]")
    res.check(s[0] <= 10 + 1e-9 and s[1] <= 10 + 1e-9, f"R ซูมสูงสุด ≤ 10 [{name}]", f"s={s[0]:.3f} แว่น={s[1]:.3f}")

    # layout ต้องนิ่ง: วางจุด/บันทึก/ข้อความเปลี่ยน แล้วช่องภาพต้องไม่ขยับหรือเปลี่ยนขนาด
    rect = "() => ['xray','fluoro'].map(k => { const r = window.__marker.viewers[k].canvas.getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; })"
    r0 = page.evaluate(rect)
    page.evaluate("() => window.__marker.viewers.xray.resetView()")
    place(page, inp, "xray", 2016, 1512)
    place(page, inp, "fluoro", 400, 300)
    page.evaluate("() => window.__marker.setFingerMode(true)")
    page.evaluate("() => window.__marker.flushSave()")
    page.wait_for_timeout(1200)                     # ให้ข้อความ "บันทึก HH:MM:SS" เปลี่ยน
    page.evaluate("() => window.__marker.setFingerMode(false)")
    r1 = page.evaluate(rect)
    res.check(r0 == r1, f"R layout นิ่ง: ช่องภาพไม่ขยับหลังวางจุด/บันทึก [{name}]", f"{r0} -> {r1}")
    page.evaluate("() => window.__marker.clearMarks()")

    # ช่องเปลี่ยนขนาดระหว่างวาง (จำลองแถบข้อความ/หน้าต่างเปลี่ยนขนาด)
    page.evaluate("() => window.__marker.viewers.xray.resetView()")
    x, y = to_page(page, "xray", 2016, 1512)
    inp.down(x, y)
    ses0 = session(page, "xray")
    page.set_viewport_size({"width": vp["width"] - 60, "height": vp["height"] - 40})
    page.wait_for_timeout(150)
    ses1 = session(page, "xray")
    inp.move(x, y, x + 20, y + 12)
    page.wait_for_timeout(50)
    inp.up(x + 20, y + 12)
    p = marks(page)["xray"][0]
    ok = ses0 is not None and ses1 is not None and p is not None and \
        abs(p["x"] - (ses0["x"] + 20 / ses0["sL"])) <= 0.06 and abs(p["y"] - (ses0["y"] + 12 / ses0["sL"])) <= 0.06
    res.check(ok, f"R ช่องเปลี่ยนขนาดระหว่างวาง ยังวางได้และจุดไม่กระโดด [{name}]",
              f"ก่อน={ses0} หลังเปลี่ยนขนาด={ses1} ได้={p}")
    check_no_ro_errors(page, res, f"[{name}] หลังเปลี่ยนขนาด")
    ctx.close()


def run_layout(pw_browser, base, targets, res: Results, name, vp, dpr, touch, tasks=(0, 1, 2, 3)):
    ctx, page = new_page(pw_browser, vp, dpr, touch)
    requests, errors = [], []
    page.on("request", lambda r: requests.append((r.method, r.url)))
    page.on("pageerror", lambda e: errors.append(str(e)))

    manifest = json.loads((GEN / "test_package" / "manifest.json").read_text(encoding="utf-8"))
    open_package(page, base, package_files("test_package"))
    wait_loaded(page)
    if touch:
        page.evaluate("() => window.__marker.setFingerMode(true)")
    kinds = ["touch", "pen"] if touch else ["mouse"]

    for i, item in enumerate(manifest["items"][:4]):
        if i not in tasks:
            continue
        if i > 0:
            goto_task(page, i)
        for which, fname in (("xray", item["xray"]), ("fluoro", item["fluoro"])):
            for t_i, (u, v) in enumerate(targets[fname]):
                kind = kinds[t_i % len(kinds)]
                inp = Input(page, ctx, kind)
                for zoom in (1, 3, 8):
                    set_zoom(page, which, zoom, u, v)
                    place_check(page, res, inp, which, u, v, f"[{name}/{kind}] {fname} ({u},{v}) ซูม {zoom}×")
                set_zoom(page, which, 5, u, v, 0.2, 0.75)
                place_check(page, res, inp, which, u, v, f"[{name}/{kind}] {fname} ({u},{v}) ซูม 5× หลังเลื่อน")

    gesture_tests(page, ctx, res, name, touch, targets, manifest)
    if not touch:
        workflow_tests(page, ctx, res, name, targets, manifest)

    outside = [(m, u) for m, u in requests if not (u.startswith(base) or u.startswith("blob:") or u.startswith("data:"))]
    posts = [(m, u) for m, u in requests if m != "GET"]
    img_fetch = [u for m, u in requests if u.startswith(base) and "/tests/" in u]
    res.check(not outside and not posts and not img_fetch, f"C เครือข่าย [{name}]",
              f"คำขอ {len(requests)} · นอกเครื่อง {outside} · ไม่ใช่ GET {posts} · โหลดภาพจากเซิร์ฟเวอร์ {img_fetch}")
    res.check(not errors, f"C ไม่มี JS error [{name}]", "; ".join(errors))
    check_no_ro_errors(page, res, f"[{name}]")
    ctx.close()


def run_blocking(pw_browser, base, res: Results):
    ctx = pw_browser.new_context(viewport={"width": 1366, "height": 768})
    page = ctx.new_page()
    cases = [
        ("bad_size_package", None, "ขนาดภาพไม่ตรง"),
        ("bad_exif_package", None, "EXIF Orientation = 6"),
        ("test_package", "T003_F.jpg", "ขาดไฟล์ภาพ 1 ไฟล์"),
        ("test_package", "manifest.json", "ไม่พบไฟล์ manifest.json"),
    ]
    for pkg, skip, expect in cases:
        open_package(page, base, package_files(pkg, skip))
        page.wait_for_selector("#errorModal:not([hidden])", timeout=5000)
        title = page.text_content("#errorTitle") or ""
        imgs = page.evaluate("() => [!!window.__marker.viewers.xray.img, !!window.__marker.viewers.fluoro.img]")
        res.check(expect in title and not any(imgs), f"C หยุดเมื่อ {pkg}{' ไม่มี ' + skip if skip else ''}",
                  f"ข้อความ: {title} · ภาพแสดงอยู่: {imgs}")
    ctx.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true", help="เปิดหน้าต่างเบราว์เซอร์ให้เห็น")
    ap.add_argument("--channel", default="msedge", help="msedge หรือ chrome")
    ap.add_argument("--quick", action="store_true", help="รันเฉพาะกลุ่ม S และ R (ลำดับจริง + ความทนทาน)")
    args = ap.parse_args()

    if not (GEN / "test_package" / "manifest.json").exists():
        sys.exit("ยังไม่มีภาพทดสอบ: รัน python tests/make_test_images.py ก่อน")
    targets = json.loads((GEN / "test_package" / "targets.json").read_text(encoding="utf-8"))["targets"]

    srv, base = start_server()
    res = Results()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=args.channel, headless=not args.headed)
        # จอโน้ตบุ๊ก Windows ที่ตั้งขยาย 137.5% / 150% (dpr ไม่ใช่จำนวนเต็ม)
        dpr_layouts = [("dpr1.375", {"width": 820, "height": 796}, 1.375),
                       ("dpr1.5", {"width": 1280, "height": 720}, 1.5),
                       ("dpr1.0", {"width": 1366, "height": 768}, 1)]
        for nm, vp, d in dpr_layouts:
            for pkg in ("test_package", "test_package_reversed"):
                sequence_tests(browser, base, res, nm, vp, d, pkg)
            robustness_tests(browser, base, res, nm, vp, d)
        robustness_tests(browser, base, res, "iPad1180", {"width": 1180, "height": 820}, 2)
        if not args.quick:
            run_layout(browser, base, targets, res, "โน้ตบุ๊ก", {"width": 1366, "height": 768}, 1, False)
            run_layout(browser, base, targets, res, "โน้ตบุ๊ก dpr1.375", {"width": 820, "height": 796}, 1.375, False, tasks=(0, 2))
            run_layout(browser, base, targets, res, "โน้ตบุ๊ก dpr1.5", {"width": 1280, "height": 720}, 1.5, False, tasks=(0, 2))
            run_layout(browser, base, targets, res, "iPad แนวนอน", {"width": 1180, "height": 820}, 2, True)
            run_layout(browser, base, targets, res, "iPad แนวตั้ง", {"width": 820, "height": 1180}, 2, True)
            run_blocking(browser, base, res)
        browser.close()
    srv.shutdown()

    for ok, label, detail in res.rows:
        if not ok:
            print(f"ไม่ผ่าน  {label}  {detail}")
    n_ok = sum(1 for r in res.rows if r[0])
    print(f"\nผ่าน {n_ok} / {len(res.rows)} รายการ")
    if res.places:
        worst = max(res.places, key=lambda t: t[1])
        print(f"  วางจุดผ่านแว่นขยาย {len(res.places)} ครั้ง: คลาดมากสุด {worst[1]:.3f} px ภาพ ({worst[3]})")
        big = [t for t in res.places if "4032" in t[3] or "T001_X" in t[3] or "T002_F" in t[3]]
        z1 = [t for t in big if "ซูม 1×" in t[3]]
        if z1:
            print(f"  ภาพ 4032 px ที่ซูม 1×: {len(z1)} ครั้ง คลาดมากสุด {max(t[1] for t in z1):.3f} px ภาพ")
        print(f"  image_px_per_screen_px มากสุด {max(t[2] for t in res.places)}")
    groups = {}
    for ok, label, _ in res.rows:
        g = label.split(" ")[0]
        groups.setdefault(g, [0, 0])
        groups[g][0] += ok
        groups[g][1] += 1
    for g, (a, b) in sorted(groups.items()):
        print(f"  กลุ่ม {g}: {a}/{b}")
    sys.exit(1 if res.fails else 0)


if __name__ == "__main__":
    main()
