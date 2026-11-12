"""ทดสอบขั้น 4–5 ในเบราว์เซอร์จริง (Edge ผ่าน Playwright)

รัน:  .venv\\Scripts\\python tests/test_workflow.py        (เพิ่ม --headed เพื่อดูหน้าจอ)

กลุ่ม
  X  กรอบ: เปิดงานแล้วเอกซเรย์ซูมพอดีกรอบ (+15%), ปุ่ม ดูทั้งภาพ / กลับไปที่กรอบ, เปิด/ปิดกรอบ
  E  งานสมจริง T006: วางผ่านแว่นขยายในมุมมองเริ่มต้น (พอดีกรอบ) ทั้ง 4 คู่ คลาด ≤ 1 px
  N  ถัดไป/มาร์กไม่ได้/บันทึก 3 คู่ พร้อมเหตุผล, จุดไม่มีคู่
  Q  เตือนจุดเกือบแนวเดียวกัน / กระจุกตัว (เอกซเรย์เทียบกรอบ)
  T  จับเวลา · P ปรับภาพ (กลับสี) ไม่กระทบพิกัด
  D  ข้อมูลห้ามหาย: บันทึกอัตโนมัติ, ปิดแท็บแล้วเปิดใหม่, หน้าแรกแสดงสถานะ, ส่งออก CSV/JSON,
     นำเข้าอีกเครื่อง, ลบ IndexedDB แล้วนำเข้า (ตรงทุกค่า), รวม/แทนที่, บังคับสำรองทุก 10 งาน + เลื่อนได้ 1 ครั้ง,
     จบงาน, โหมดส่วนตัว (จำลอง) ต้องห้ามเริ่มงาน
  C  ไม่มีคำขอเครือข่ายออกนอกเครื่อง / ไม่มี error ในหน้า
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import shutil
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_coordinates import (GEN, ERR_INIT, Input, Results, goto_task, marks, open_package,  # noqa: E402
                              package_files, place, start_server, to_page, view, wait_loaded)

DL = GEN / "_downloads"
PKG = "test_package"


class Env:
    def __init__(self, browser, base, res):
        self.browser, self.base, self.res = browser, base, res
        self.requests = []

    def ctx(self, vp=None, init=None):
        c = self.browser.new_context(viewport=vp or {"width": 1366, "height": 768}, accept_downloads=True)
        c.add_init_script(ERR_INIT)
        if init:
            c.add_init_script(init)
        c.on("request", lambda r: self.requests.append((r.method, r.url)))
        return c

    def page(self, c):
        p = c.new_page()
        p.goto(f"{self.base}/marker/index.html")
        p.wait_for_selector("body[data-ready='1']")
        return p


def manifest(pkg=PKG):
    return json.loads((GEN / pkg / "manifest.json").read_text(encoding="utf-8"))


def targets(pkg=PKG):
    return json.loads((GEN / pkg / "targets.json").read_text(encoding="utf-8"))["targets"]


def open_pkg(page, pkg=PKG):
    open_package(page, None, package_files(pkg), goto=False)
    wait_loaded(page)


def wait_dialog(page):
    page.wait_for_selector("#dialog:not([hidden])", timeout=5000)
    return page.text_content("#dialogTitle") or ""


def choose_reason(page, code, text=None):
    wait_dialog(page)
    page.check(f"#dialog input[value='{code}']")
    if text:
        page.fill("#dialog .text-input", text)
    page.click("#btnReasonOk")


def flush(page):
    page.evaluate("() => window.__marker.flushSave()")


def idb_record(page, pkg):
    return page.evaluate("(id) => window.Store.get(id)", pkg)


def download(page, selector, name):
    with page.expect_download() as d:
        page.click(selector)
    dl = d.value
    DL.mkdir(parents=True, exist_ok=True)
    path = DL / f"{name}_{dl.suggested_filename}"
    dl.save_as(str(path))
    return dl.suggested_filename, path


def place_pairs(page, inp, pairs):
    """pairs = [((xu,xv),(fu,fv)), ...] วางตามลำดับ เอกซเรย์ แล้ว ฟลู"""
    for (xu, xv), (fu, fv) in pairs:
        place(page, inp, "xray", xu, xv)
        place(page, inp, "fluoro", fu, fv)


def show_whole(page):
    page.evaluate("() => { window.__marker.viewers.xray.resetView(); window.__marker.viewers.fluoro.resetView(); }")


# ---------------------------------------------------------------- X, E
def test_box_and_realistic(env: Env):
    res = env.res
    c = env.ctx({"width": 820, "height": 796})
    p = env.page(c)
    open_pkg(p)
    m = manifest()
    b = m["items"][0]["box_xyxy"]
    v = view(p, "xray")
    x1, y1 = v["tx"] + b[0] * v["s"], v["ty"] + b[1] * v["s"]
    x2, y2 = v["tx"] + b[2] * v["s"], v["ty"] + b[3] * v["s"]
    bw, bh = (b[2] - b[0]) * 1.3, (b[3] - b[1]) * 1.3
    s_expect = min(v["cssW"] / bw, v["cssH"] / bh)
    inside = x1 >= 0 and y1 >= 0 and x2 <= v["cssW"] and y2 <= v["cssH"]
    res.check(inside and abs(v["s"] - s_expect) < 1e-6 and abs((x1 + x2) / 2 - v["cssW"] / 2) < 0.01,
              "X เปิดงานแล้วซูมพอดีกรอบ +15%", f"s={v['s']:.4f} ควร {s_expect:.4f} · กรอบบนจอ ({x1:.0f},{y1:.0f})-({x2:.0f},{y2:.0f})")
    p.click("#btnXView")
    w = view(p, "xray")
    lbl = p.text_content("#btnXView")
    res.check(abs(w["s"] - w["fit"]) < 1e-9 and "กลับไปที่กรอบ" in lbl, "X ปุ่ม ดูทั้งภาพ", f"s={w['s']:.4f} fit={w['fit']:.4f} ปุ่ม='{lbl}'")
    p.click("#btnXView")
    w2 = view(p, "xray")
    res.check(abs(w2["s"] - v["s"]) < 1e-9 and "ดูทั้งภาพ" in p.text_content("#btnXView"), "X ปุ่ม กลับไปที่กรอบ", f"s={w2['s']:.4f}")
    p.click("[data-adjust='xray']")
    p.uncheck("#chkBox")
    off = p.evaluate("() => window.__marker.state.showBox")
    p.check("#chkBox")
    res.check(off is False and p.evaluate("() => window.__marker.state.showBox") is True, "X เปิด/ปิดกรอบ", "")
    p.click("#adjustX [data-adjust-close]")

    # งานสมจริง T006: ไม่แตะมุมมอง (ใช้มุมมองเริ่มต้นที่พอดีกรอบ)
    real_idx = next(i for i, it in enumerate(m["items"]) if it["task_id"] == "T006")
    goto_task(p, real_idx)
    t = targets()
    inp = Input(p, c, "mouse")
    xt, ft = t["T006_X.png"], t["T006_F.jpg"]
    errs = []
    for k in range(4):
        for side, (u, vv) in (("xray", xt[k]), ("fluoro", ft[k])):
            place(p, inp, side, u, vv)
            pt = marks(p)[side][k]
            errs.append(math.hypot(pt["x"] - u, pt["y"] - vv) if pt else 99)
    res.check(max(errs) <= 1.0, "E งานสมจริง T006 วาง 4 คู่ในมุมมองพอดีกรอบ", f"คลาดมากสุด {max(errs):.2f} px")
    p.click("#btnNext")
    title = wait_dialog(p)
    p.click("#dialogButtons button:has-text('อยู่ที่งานนี้')")
    res.check("งานสุดท้าย" in title and marks(p)["status"] == "done", "N งานสุดท้าย: ครบ 4 คู่ = done แล้วถามไปต่อ",
              f"dialog='{title}' status={marks(p)['status']}")
    c.close()


# ---------------------------------------------------------------- N, Q, T, P
def test_navigation_quality(env: Env):
    res = env.res
    c = env.ctx()
    p = env.page(c)
    open_pkg(p)
    show_whole(p)
    inp = Input(p, c, "mouse")
    t = targets()
    xt, ft = t["T001_X.png"], t["T001_F.jpg"]

    p.click("#btnNext")
    p.wait_for_timeout(100)
    res.check(p.evaluate("() => window.__marker.state.index") == 0 and "ยังไม่ครบ" in (p.text_content("#toast") or ""),
              "N ถัดไปตอนยังไม่ครบ = ไม่ไป", p.text_content("#toast") or "")

    place_pairs(p, inp, list(zip(xt[:3], ft[:3])))
    place(p, inp, "xray", *xt[3])                              # จุดไม่มีคู่
    p.click("#btnNext")
    p.wait_for_timeout(100)
    res.check(p.evaluate("() => window.__marker.state.index") == 0 and "ไม่มีคู่" in (p.text_content("#toast") or ""),
              "N มีจุดไม่มีคู่ = ไม่ไป", p.text_content("#toast") or "")
    p.evaluate("() => window.__marker.undo()")

    p.click("#btnNext")
    title = wait_dialog(p)
    va_partial = p.locator("#dialog input[value='view_angle']").count() == 1 and "มุมถ่ายต่างกันมาก" in (p.text_content("#dialog") or "")
    p.click("#btnReasonOk")                                    # ยังไม่เลือก
    err1 = p.text_content("#dialog .err-text")
    choose_reason(p, "no_4th_point")
    p.wait_for_function("() => window.__marker.state.index === 1 && window.__marker.viewers.xray.img")
    t0 = p.evaluate("() => window.__marker.state.tasks['T001']")
    res.check("3 คู่" in title and "เลือกเหตุผล" in err1 and t0["status"] == "partial" and t0["reason"] == "no_4th_point",
              "N บันทึก 3 คู่ + เหตุผล = partial", f"{title} · {err1} · {t0['status']} {t0['reason']}")

    p.click("#btnUnmarkable")
    wait_dialog(p)
    va_unm = p.locator("#dialog input[value='view_angle']").count() == 1 and "มุมถ่ายต่างกันมาก" in (p.text_content("#dialog") or "")
    res.check(va_partial and va_unm, "N เหตุผล 'มุมถ่ายต่างกันมาก' มีทั้งใน 3 คู่ และ มาร์กไม่ได้", f"partial={va_partial} unmarkable={va_unm}")
    p.check("#dialog input[value='other']")
    p.click("#btnReasonOk")
    err2 = p.text_content("#dialog .err-text")
    p.fill("#dialog .text-input", "ภาพเบลอมาก # ทดสอบ, มีจุลภาค")
    p.click("#btnReasonOk")
    p.wait_for_function("() => window.__marker.state.index === 2 && window.__marker.viewers.xray.img")
    t1 = p.evaluate("() => window.__marker.state.tasks['T002']")
    res.check("พิมพ์เหตุผล" in err2 and t1["status"] == "unmarkable" and t1["reason"] == "other" and "เบลอ" in t1["reason_text"],
              "N มาร์กไม่ได้ + อื่นๆ ต้องพิมพ์เหตุผล", f"{err2} · {t1['status']} {t1['reason_text']}")
    res.check("ทำแล้ว 2/" in (p.text_content("#progress") or ""), "N ความคืบหน้าบนแถบบน", p.text_content("#progress") or "")

    # Q: เตือนการกระจาย (งาน T003 เอกซเรย์ 3024x4032 กรอบ ~1663x2218)
    show_whole(p)
    pk = manifest()["items"][2]["box_xyxy"]
    cx, cy = (pk[0] + pk[2]) / 2, (pk[1] + pk[3]) / 2
    fpts = [(150, 150), (450, 200), (300, 650)]
    place_pairs(p, inp, [((cx - 600, cy), fpts[0]), ((cx, cy + 8), fpts[1]), ((cx + 600, cy + 16), fpts[2])])
    w1 = p.text_content("#warnText") or ""
    p.evaluate("() => window.__marker.clearMarks()")
    # ซูมเข้า (1 px จอ = 1 px ภาพ) ก่อนวางจุดที่อยู่ใกล้กัน ไม่งั้นการกดจะโดนจุดเดิม (= ลากจุดเดิม)
    p.evaluate(f"() => {{ const q = window.__marker.viewers.xray; q.setView(1, q.cssW / 2 - {cx} - 30, q.cssH / 2 - {cy} - 30); }}")
    place_pairs(p, inp, [((cx, cy), fpts[0]), ((cx + 60, cy), fpts[1]), ((cx + 30, cy + 60), fpts[2])])
    w2 = p.text_content("#warnText") or ""
    show_whole(p)
    p.evaluate("() => window.__marker.clearMarks()")
    place_pairs(p, inp, [((cx - 600, cy - 800), fpts[0]), ((cx + 600, cy - 700), fpts[1]), ((cx, cy + 800), fpts[2])])
    w3 = p.text_content("#warnText") or ""
    res.check("แนวเดียวกัน" in w1 and "เอกซเรย์" in w1, "Q เตือนจุดเกือบแนวเดียวกัน", w1)
    res.check("กระจุก" in w2 and "กรอบ" in w2, "Q เตือนจุดกระจุก (เทียบกรอบ)", w2)
    res.check(w3 == "", "Q จุดกระจายดี = ไม่เตือน", w3)

    # T: เวลา
    d0 = p.evaluate("() => window.__marker.task().duration_ms")
    for _ in range(3):
        p.mouse.move(400, 400)
        p.wait_for_timeout(1000)
    d1 = p.evaluate("() => window.__marker.task().duration_ms")
    st = p.evaluate("() => window.__marker.state.tasks['T001'].started_at")   # (งานนี้ถูก clearMarks ในเทสต์ จึงดู T001)
    res.check(d1 - d0 >= 2000 and st, "T จับเวลาตอนใช้งาน", f"{d0} -> {d1} ms · started_at={st}")

    # P: กลับสีฟลู ไม่กระทบพิกัด
    pix = "() => { const v = window.__marker.viewers.fluoro; v.render(); const c = v.canvas; return Array.from(c.getContext('2d').getImageData(Math.floor(c.width/2)+40, Math.floor(c.height/2)+40, 1, 1).data.slice(0,3)); }"
    before = p.evaluate(pix)
    p.click("[data-adjust='fluoro']")
    p.check("#adjustF input[data-k='invert']")
    p.wait_for_function("() => !!window.__marker.viewers.fluoro._src")
    after = p.evaluate(pix)
    view_before = view(p, "fluoro")
    p.click("#adjustF [data-adjust-close]")
    p.evaluate("() => window.__marker.clearMarks()")
    place(p, inp, "xray", cx, cy)
    place(p, inp, "fluoro", *targets()["T003_F.jpg"][0])
    fp = marks(p)["fluoro"][0]
    u, vv = targets()["T003_F.jpg"][0]
    inv_ok = all(abs((255 - a) - b2) <= 3 for a, b2 in zip(before, after))
    res.check(inv_ok and abs(fp["x"] - u) <= 1 and abs(fp["y"] - vv) <= 1 and view_before["s"] == view(p, "fluoro")["s"],
              "P กลับสีภาพฟลู (แสดงผลเท่านั้น) พิกัดยังถูก", f"pixel {before} -> {after} · จุด ({fp['x']},{fp['y']}) ควร ({u},{vv})")
    p.click("[data-adjust='fluoro']")
    p.click("#adjustF [data-adjust-reset]")
    check_page_errors(p, res, "หน้าทดสอบนำทาง")
    c.close()


def check_page_errors(p, res, label):
    errs = p.evaluate("() => window.__errs || []")
    res.check(not errs, f"C ไม่มี error ในหน้า ({label})", str(errs[:3]))


# ---------------------------------------------------------------- D
def tasks_equal(a, b):
    return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False)


def test_data_safety(env: Env):
    res = env.res
    m = manifest()
    t = targets()
    c = env.ctx()
    p = env.page(c)
    res.check(p.is_visible("#noDataBox"), "D เครื่องใหม่: แสดงปุ่ม นำเข้าไฟล์สำรอง ชัดเจน", "")
    open_pkg(p)
    show_whole(p)
    inp = Input(p, c, "mouse")
    place_pairs(p, inp, list(zip(t["T001_X.png"][:4], t["T001_F.jpg"][:4])))
    p.click("#btnNext")
    p.wait_for_function("() => window.__marker.state.index === 1 && window.__marker.viewers.xray.img")
    show_whole(p)
    place_pairs(p, inp, list(zip(t["T002_X.jpg"][:2], t["T002_F.jpg"][:2])))
    # หมายเหตุต่องาน (ไม่บังคับ): ข้อความมี # , ขึ้นบรรทัดใหม่ ต้องไม่ทำให้ CSV เพี้ยน
    st_before = p.evaluate("() => window.__marker.task().status")
    p.click("#btnNote")
    wait_dialog(p)
    p.fill("#noteInput", "จุด 2 ไม่แน่ใจ # ทดสอบ, \"อ้าง\"\nบรรทัดสอง")
    p.click("#btnNoteOk")
    p.wait_for_timeout(100)
    tn = p.evaluate("() => window.__marker.task()")
    res.check(tn["note"] == 'จุด 2 ไม่แน่ใจ # ทดสอบ, "อ้าง" บรรทัดสอง' and tn["status"] == st_before
              and "✓" in (p.text_content("#btnNote") or ""),
              "D หมายเหตุต่องาน: บันทึกได้ ไม่เปลี่ยนสถานะ ปุ่มแสดง ✓", f"{tn['note']!r} {st_before}->{tn['status']}")
    flush(p)
    rec = idb_record(p, m["package_id"])
    res.check(rec and rec["tasks"]["T001"]["status"] == "done" and rec["tasks"]["T002"]["fluoro"][1] is not None,
              "D บันทึกอัตโนมัติลง IndexedDB ทุกการเปลี่ยนแปลง", f"T001={rec and rec['tasks']['T001']['status']}")
    snapshot = p.evaluate("() => JSON.parse(JSON.stringify(window.__marker.state.tasks))")

    # ปิดแท็บแล้วเปิดใหม่
    p.close()
    p = env.page(c)
    item = p.text_content("#savedList") or ""
    res.check(m["package_id"] in item and "ทำแล้ว 1/" in item and "บันทึกล่าสุด" in item and "ยังไม่เคยสำรอง" in item,
              "D หน้าแรกแสดง: บันทึกล่าสุด / ทำแล้ว / สำรองล่าสุด", item.replace("\n", " "))
    open_pkg(p)
    restored = p.evaluate("() => JSON.parse(JSON.stringify(window.__marker.state.tasks))")
    same_points = all(tasks_equal(restored[k]["xray"], snapshot[k]["xray"]) and tasks_equal(restored[k]["fluoro"], snapshot[k]["fluoro"])
                      and restored[k]["status"] == snapshot[k]["status"] for k in snapshot)
    res.check(same_points and p.evaluate("() => window.__marker.state.index") == 1,
              "D ปิดแท็บกลางงานแล้วเปิดใหม่ ข้อมูลอยู่ครบ + กลับไปงานเดิม", "")

    # ส่งออก JSON + CSV
    p.click("#btnExport")
    wait_dialog(p)
    jname, jpath = download(p, "#btnDlJson", "export1")
    cname, cpath = download(p, "#btnDlCsv", "export1")
    p.click("#btnExportClose")
    total = len(m["items"])
    res.check(re.fullmatch(rf"marks_{m['package_id']}_\d{{8}}-\d{{6}}_1of{total}\.json", jname) is not None,
              "D ชื่อไฟล์สำรองมีวันที่ เวลา และจำนวนงานที่ทำแล้ว", jname)
    data = json.loads(jpath.read_text(encoding="utf-8"))
    res.check(data["format"] == "pelnav-marks" and "COCO" in data["coord_convention"] and data["package_id"] == m["package_id"],
              "D ไฟล์ JSON มีรูปแบบและมาตรฐานพิกัด", data.get("coord_convention", "")[:60])
    check_csv(res, cpath, data, m)
    rec = idb_record(p, m["package_id"])
    res.check(rec["last_backup_at"] is not None, "D บันทึกเวลาสำรองล่าสุด", str(rec["last_backup_at"]))

    # นำเข้าบนอีกเครื่อง (context ใหม่ = เครื่องใหม่)
    c2 = env.ctx()
    p2 = env.page(c2)
    p2.set_input_files("#noDataBox .inputBackup", str(jpath))
    wait_dialog(p2)
    p2.click("#btnImportReplace")
    p2.wait_for_function("(id) => window.Store.get(id).then(r => !!r)", arg=m["package_id"])
    r2 = idb_record(p2, m["package_id"])
    res.check(tasks_equal(r2["tasks"], data["tasks"]), "D ส่งออก → นำเข้าอีกเครื่อง ข้อมูลตรงทุกค่า", "")
    open_pkg(p2)
    res.check(p2.evaluate("() => window.__marker.state.tasks['T001'].status") == "done", "D เปิดแพ็กเกจหลังนำเข้า ทำต่อได้", "")
    c2.close()

    # ลบ IndexedDB ทิ้ง -> นำเข้า -> ตรงทุกค่า (acceptance test 8)
    p.evaluate("() => new Promise((ok, bad) => { const r = indexedDB.deleteDatabase('pelnav-marker'); r.onsuccess = ok; r.onerror = bad; r.onblocked = () => ok(); })")
    p.reload()
    p.wait_for_selector("body[data-ready='1']")
    empty = p.is_visible("#noDataBox")
    p.set_input_files("#noDataBox .inputBackup", str(jpath))
    wait_dialog(p)
    p.click("#btnImportReplace")
    p.wait_for_function("(id) => window.Store.get(id).then(r => !!r)", arg=m["package_id"])
    r3 = idb_record(p, m["package_id"])
    res.check(empty and tasks_equal(r3["tasks"], data["tasks"]), "D ลบ IndexedDB → นำเข้าไฟล์สำรอง → ข้อมูลกลับมาครบตรงทุกค่า",
              f"หน้าแรกว่าง={empty}")

    # รวม / แทนที่: แก้งานในเครื่องหลังส่งออก แล้วนำเข้าไฟล์เก่า
    open_pkg(p)
    goto_task(p, 2)
    show_whole(p)
    inp = Input(p, c, "mouse")
    place(p, inp, "xray", *t["T003_X.png"][0])
    goto_task(p, 1)
    show_whole(p)
    place(p, inp, "xray", *t["T002_X.jpg"][2])                 # T002 ในเครื่องใหม่กว่าไฟล์
    flush(p)
    local_t2 = p.evaluate("() => JSON.parse(JSON.stringify(window.__marker.state.tasks['T002']))")
    p.click("#btnOpen")
    p.set_input_files("#backupLabel .inputBackup", str(jpath))
    title = wait_dialog(p)
    body = p.text_content("#dialogBody") or ""
    p.click("#btnImportMerge")
    p.wait_for_timeout(300)
    r4 = idb_record(p, m["package_id"])
    # T001: จุดเหมือนไฟล์ (เวลาที่ใช้ในเครื่องอาจเพิ่มหลังส่งออก -> ถือว่าในเครื่องใหม่กว่า/เท่ากัน ก็ยึดในเครื่อง)
    t1_same_points = tasks_equal(r4["tasks"]["T001"]["xray"], data["tasks"]["T001"]["xray"]) and \
        tasks_equal(r4["tasks"]["T001"]["fluoro"], data["tasks"]["T001"]["fluoro"])
    res.check("มีข้อมูลในเครื่องอยู่แล้ว" in title and "คงของในเครื่องที่ใหม่กว่า" in body and tasks_equal(r4["tasks"]["T002"], local_t2)
              and "T003" in r4["tasks"] and t1_same_points,
              "D นำเข้าแบบ รวม: แสดงสรุปก่อนยืนยัน + ยึดงานที่แก้ล่าสุด", body[:200])
    p.set_input_files("#backupLabel .inputBackup", str(jpath))      # หน้าแรกยังเปิดอยู่
    wait_dialog(p)
    p.click("#btnImportReplace")
    p.wait_for_timeout(300)
    r5 = idb_record(p, m["package_id"])
    snaps = p.evaluate("() => new Promise(ok => { const r = indexedDB.open('pelnav-marker'); r.onsuccess = () => { const q = r.result.transaction('snapshots').objectStore('snapshots').count(); q.onsuccess = () => ok(q.result); }; })")
    res.check(tasks_equal(r5["tasks"], data["tasks"]) and snaps >= 2, "D นำเข้าแบบ แทนที่ = ตรงกับไฟล์ + เก็บสำเนาก่อนนำเข้า",
              f"snapshots={snaps}")
    check_page_errors(p, res, "หน้าทดสอบข้อมูล")
    c.close()


def check_csv(res, path, data, m):
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    lines = text.splitlines()
    meta = [l for l in lines if l.startswith("#")]
    body = "\n".join(l for l in lines if not l.startswith("#"))
    rows = list(csv.DictReader(io.StringIO(body)))
    res.check(raw.startswith(b"\xef\xbb\xbf") and any("coord_convention" in l and "COCO" in l for l in meta)
              and any("subtract 0.5" in l for l in meta), "D CSV: หัวไฟล์ระบุมาตรฐานพิกัด COCO", meta[4][:80] if len(meta) > 4 else str(meta))
    cols = rows[0].keys() if rows else []
    need = {"note", "task_id", "point_id", "xray_x", "xray_y", "fluoro_x", "fluoro_y", "status", "reason", "started_at",
            "finished_at", "duration_s", "app_version", "package_id", "xray_image_px_per_screen_px", "fluoro_image_px_per_screen_px"}
    res.check(need <= set(cols), "D CSV: มีคอลัมน์ครบตามสเปก + image_px_per_screen_px", str(sorted(set(need) - set(cols))))
    exp = []
    for it in m["items"]:
        tk = data["tasks"].get(it["task_id"])
        if not tk or (tk["status"] == "todo" and not tk.get("note")):
            continue
        pairs = [i for i in range(4) if tk["xray"][i] and tk["fluoro"][i]]
        exp += [(it["task_id"], str(i + 1)) for i in pairs] or [(it["task_id"], "")]
    got = [(r["task_id"], r["point_id"]) for r in rows]
    vals_ok = True
    for r in rows:
        if not r["point_id"]:
            continue
        tk = data["tasks"][r["task_id"]]
        i = int(r["point_id"]) - 1
        vals_ok &= r["xray_x"] == f"{tk['xray'][i]['x']:.1f}" and r["fluoro_y"] == f"{tk['fluoro'][i]['y']:.1f}"
        vals_ok &= float(r["xray_image_px_per_screen_px"]) <= 0.5
    for r in rows:
        note = data["tasks"][r["task_id"]].get("note") or ""
        vals_ok &= r["note"] == note.replace("#", "＃")
    res.check(got == exp and vals_ok, "D CSV: แถวและค่าตรงกับข้อมูล (ทศนิยม 1 ตำแหน่ง) + หมายเหตุ", f"ได้ {got} ควร {exp}")
    res.check(any(r["note"] for r in rows), "D CSV: มีคอลัมน์หมายเหตุและค่าตรงกับ JSON", str([r["note"] for r in rows]))


def test_forced_backup(env: Env):
    res = env.res
    pkg = "test_package_big"
    c = env.ctx()
    p = env.page(c)
    open_pkg(p, pkg)
    titles = []
    for i in range(10):
        p.click("#btnUnmarkable")
        choose_reason(p, "unclear")
        if i < 9:
            p.wait_for_function(f"() => window.__marker.state.index === {i + 1}")
    title = wait_dialog(p)
    has_snooze = p.is_visible("#btnSnooze")
    res.check("สำรอง" in title and has_snooze, "D ครบ 10 งาน → บังคับสำรอง (มีปุ่ม เลื่อนไปก่อน)", title)
    p.click("#btnSnooze")
    p.wait_for_function("() => window.__marker.state.index === 10")
    p.click("#btnUnmarkable")
    choose_reason(p, "unclear")
    wait_dialog(p)
    no_snooze = not p.is_visible("#btnSnooze") and not p.is_visible("#btnExportClose")
    name, path = download(p, "#btnDlJson", "forced")
    p.wait_for_function("() => window.__marker.state.index === 11")
    res.check(no_snooze and re.search(r"_11of12\.json$", name) is not None, "D เลื่อนได้ 1 ครั้ง แล้วต้องดาวน์โหลด", name)
    # จบงาน -> บังคับสำรองอีก แล้วกลับหน้าแรก
    p.click("#btnFinish")
    title = wait_dialog(p)
    name2, _ = download(p, "#btnDlJson", "finish")
    p.wait_for_selector("#startScreen:not([hidden])")
    p.wait_for_function("() => !document.getElementById('savedList').textContent.includes('ยังไม่เคยสำรอง')")
    saved = p.text_content("#savedList") or ""
    res.check("สำรอง" in title and name2.endswith("_11of12.json") and "สำรองล่าสุด" in saved,
              "D กดจบงาน → บังคับสำรอง → กลับหน้าแรกพร้อมสถานะ", saved.replace("\n", " ")[:150])
    check_page_errors(p, res, "หน้าทดสอบสำรอง")
    c.close()


FAKE_LOST_FILES = """() => {
  // จำลอง iPad ปล่อยไฟล์ที่เลือกไว้: อ่านแล้วได้ NotReadableError เหมือนบน iOS
  const st = window.__marker.state;
  const fake = (n) => ({ name: n, size: 10, slice: () => ({ arrayBuffer: () =>
      Promise.reject(new DOMException('The I/O read operation failed.', 'NotReadableError')) }) });
  for (const k of [...st.byName.keys()]) st.byName.set(k, fake(k));
}"""


def repick(p):
    """กดปุ่ม 'เลือกไฟล์แพ็กเกจอีกครั้ง' -> ต้องสั่งเปิดตัวเลือกไฟล์ (#inputFiles.click) แล้วใส่ไฟล์เข้าไป
    (ไม่ใช้ expect_file_chooser เพราะทำให้ Playwright ค้างตอนปิด)"""
    p.evaluate("""() => { window.__picked = 0; const o = HTMLInputElement.prototype.click;
        HTMLInputElement.prototype.click = function () { if (this.id === 'inputFiles') window.__picked++; }; }""")
    p.click("#btnRepick")
    assert p.evaluate("() => window.__picked") == 1, "ปุ่มไม่ได้เปิดตัวเลือกไฟล์"
    p.set_input_files("#inputFiles", package_files(PKG))


def test_ios_resilience(env: Env):
    """ปัญหาที่เจอบน iPad จริง (iPadOS 26.4): การเชื่อมต่อ IndexedDB ถูกตัด, บันทึกล้มเหลวชั่วคราว,
    iPad ปล่อยไฟล์ภาพหลังดาวน์โหลด, 'Script error.' จากนอกเว็บ"""
    res = env.res
    m = manifest()
    t = targets()
    c = env.ctx(init=NO_LOCAL_IMAGES)        # ทดสอบโหมดอ่านจากไฟล์ที่เลือก (กรณีเก็บภาพในเครื่องไม่ได้)
    p = env.page(c)
    open_pkg(p)
    show_whole(p)
    inp = Input(p, c, "mouse")
    place_pairs(p, inp, [(t["T001_X.png"][0], t["T001_F.jpg"][0])])
    flush(p)

    # 1) การเชื่อมต่อฐานข้อมูลถูกปิด (เหมือน iOS ตัดตอนแอปถูกพัก) -> ต้องเปิดใหม่และบันทึกได้เอง
    p.evaluate("async () => { const db = await window.Store._db(); db.close(); }")
    place_pairs(p, inp, [(t["T001_X.png"][1], t["T001_F.jpg"][1])])
    flush(p)
    rec = idb_record(p, m["package_id"])
    label = p.text_content("#saveLabel") or ""
    res.check(rec["tasks"]["T001"]["xray"][1] is not None and "ไม่สำเร็จ" not in label,
              "I การเชื่อมต่อฐานข้อมูลถูกตัด → เปิดใหม่และบันทึกได้เอง", label)

    # 2) บันทึกล้มเหลวหลายครั้ง (error = null แบบ Safari) -> ลองใหม่เอง แล้วข้อมูลครบเมื่อกลับมาใช้ได้
    p.evaluate("""() => { window.__realPut = window.Store.put; let n = 0;
        window.Store.put = (r) => (n++ < 3 ? Promise.reject(null) : window.__realPut(r)); }""")
    place_pairs(p, inp, [(t["T001_X.png"][2], t["T001_F.jpg"][2])])
    p.wait_for_timeout(300)
    mid = p.text_content("#saveLabel") or ""
    log_ok = p.evaluate("() => window.__marker.Debug.entries().some(e => e.msg.includes('บันทึกไม่สำเร็จ') && !e.msg.endsWith('null'))")
    p.wait_for_function("() => (document.getElementById('saveLabel').textContent || '').startsWith('บันทึก ')", timeout=15000)
    p.evaluate("() => { window.Store.put = window.__realPut; }")
    flush(p)
    rec = idb_record(p, m["package_id"])
    res.check(rec["tasks"]["T001"]["xray"][2] is not None and rec["tasks"]["T001"]["fluoro"][2] is not None and log_ok,
              "I บันทึกล้มเหลวชั่วคราว → ลองใหม่เอง ข้อมูลครบ (log ไม่ใช่ 'null')", f"ระหว่างล้ม: '{mid}'")

    # 3) iPad ปล่อยไฟล์ภาพ ตอนไปงานถัดไป -> ข้อความชัด + เลือกไฟล์ใหม่ แล้วกลับมางานเดิม จุดไม่หาย
    p.evaluate(FAKE_LOST_FILES)
    # ไม่ await: showTask จะรอจนกว่าจะกดปุ่มในหน้าต่าง (ถ้า await ตรงนี้ Playwright จะค้าง)
    p.evaluate("() => { window.__marker.showTask(1); }")
    title = wait_dialog(p)
    body = p.text_content("#dialogBody") or ""
    repick(p)
    p.wait_for_function("() => window.__marker.state.index === 1 && window.__marker.viewers.xray.img && window.__marker.state.imagesReady")
    kept = p.evaluate("() => window.__marker.state.tasks['T001'].xray.filter(Boolean).length")
    res.check("เลือกไฟล์แพ็กเกจอีกครั้ง" in title and "ไม่หาย" in body and kept == 3,
              "I iPad ปล่อยไฟล์ภาพ → บอกให้เลือกไฟล์ใหม่ → กลับมางานเดิม จุดอยู่ครบ", f"{title} · จุด T001 = {kept}")

    # 4) ปล่อยไฟล์ระหว่างไปหน้าดาวน์โหลด -> กลับมาที่เว็บ (focus) ต้องเตือนทันที
    p.evaluate(FAKE_LOST_FILES)
    p.evaluate("() => window.dispatchEvent(new Event('focus'))")
    title2 = wait_dialog(p)
    repick(p)
    p.wait_for_function("() => window.__marker.state.imagesReady")
    res.check("เลือกไฟล์แพ็กเกจอีกครั้ง" in title2, "I กลับมาที่เว็บหลังดาวน์โหลด → ตรวจไฟล์และเตือนทันที", title2)
    check_page_errors(p, res, "หน้าทดสอบ iPad")

    # 5) 'Script error.' จากนอกเว็บ -> บันทึกเป็นข้อมูล ไม่ใช่ข้อผิดพลาดของเว็บ
    p.evaluate("() => window.dispatchEvent(new ErrorEvent('error', { message: 'Script error.' }))")
    last = p.evaluate("() => window.__marker.Debug.entries().slice(-1)[0]")
    res.check(not last["isErr"] and "นอกเว็บ" in last["msg"], "I 'Script error.' จากนอกเว็บ ไม่นับเป็นข้อผิดพลาด", last["msg"])
    c.close()


NO_LOCAL_IMAGES = "window.__PELNAV_NO_LOCAL_IMAGES = true;"

# แก้ฐานข้อมูลภาพในเครื่องโดยตรง (จำลองภาพหาย/เสีย)
IMG_DB_OP = """async ([op, pkg, name]) => {
  const db = await new Promise((ok, bad) => { const r = indexedDB.open('pelnav-images'); r.onsuccess = () => ok(r.result); r.onerror = bad; });
  await new Promise((ok, bad) => {
    const t = db.transaction('files', 'readwrite'), s = t.objectStore('files'), key = pkg + '/' + name;
    if (op === 'delete') s.delete(key);
    else s.get(key).onsuccess = (e) => { const v = e.target.result; v.blob = new Blob([new Uint8Array(v.size)], { type: v.blob.type }); s.put(v); };
    t.oncomplete = ok; t.onerror = bad;
  });
  db.close();
}"""
DROP_IMG_DB = """() => new Promise((ok) => { window.ImageStore._close().then(() => {
  const r = indexedDB.deleteDatabase('pelnav-images'); r.onsuccess = ok; r.onerror = ok; r.onblocked = ok; }); })"""
# จำนวนภาพและแพ็กเกจที่เหลือในฐานข้อมูลภาพ (หลังลบ หน้าแรกอาจเปิดฐานข้อมูลเปล่าขึ้นใหม่ได้ ไม่มีภาพ)
IMG_DB_COUNT = """() => new Promise((ok) => { const r = indexedDB.open('pelnav-images');
  r.onupgradeneeded = () => { r.transaction.abort(); };
  r.onerror = () => ok(0);
  r.onsuccess = () => { const db = r.result; if (!db.objectStoreNames.contains('files')) { db.close(); ok(0); return; }
    const t = db.transaction(['files', 'packages']); let n = 0;
    t.objectStore('files').count().onsuccess = (e) => { n += e.target.result; };
    t.objectStore('packages').count().onsuccess = (e) => { n += e.target.result; };
    t.oncomplete = () => { db.close(); ok(n); }; }; })"""
USAGE = "() => navigator.storage.estimate().then(e => e.usage)"


def local_state(p, pkg):
    return p.evaluate("""async (pkg) => { const r = await window.ImageStore.getRecord(pkg);
        const n = (await window.ImageStore.storedNames(pkg)).length;
        return { complete: !!(r && r.complete), stored: n, flag: window.ImageStore.flag(), source: window.__marker.state.source }; }""", pkg)


def test_local_images(env: Env):
    """แบบ A: เปิดแพ็กเกจครั้งแรกเก็บภาพในเครื่อง → ครั้งต่อไปกด ทำงานต่อ ไม่ต้องเลือกไฟล์
    ตรวจความครบทุกครั้งที่เปิด, ภาพหาย/เสีย → ให้เลือกแพ็กเกจใหม่ จุดไม่หาย, ลบภาพ (ยืนยัน 2 ครั้ง) ไม่ลบจุด"""
    res = env.res
    m = manifest()
    pkg = m["package_id"]
    nfiles = 2 * len(m["items"])
    t = targets()
    c = env.ctx()
    p = env.page(c)
    u0 = p.evaluate(USAGE)

    # 1) เปิดครั้งแรก: คัดลอกภาพเข้าเครื่อง พร้อมแถบความคืบหน้า
    open_pkg(p)
    p.wait_for_function("() => window.__marker.state.source === 'local'", timeout=15000)
    ls = local_state(p, pkg)
    bar = p.evaluate("() => { const b = document.getElementById('importBar'); return [b.value, b.max]; }")
    res.check(ls["complete"] and ls["stored"] == nfiles and ls["flag"] == pkg and bar == [nfiles, nfiles],
              "L เปิดครั้งแรก: เก็บภาพในเครื่องครบทุกไฟล์ + แถบความคืบหน้าถึง 100%", f"{ls} bar={bar}")
    show_whole(p)
    inp = Input(p, c, "mouse")
    place_pairs(p, inp, [(t["T001_X.png"][0], t["T001_F.jpg"][0])])
    flush(p)
    u1 = p.evaluate(USAGE)

    # 2) ปิดแล้วเปิดใหม่ (= แตะไอคอน): กด ทำงานต่อ ได้เลย ไม่ต้องเลือกไฟล์
    p.close()
    p = env.page(c)
    p.wait_for_selector("#btnResume", timeout=5000)
    box = p.text_content("#localBox") or ""
    p.click("#btnResume")
    p.wait_for_function("() => window.__marker.state.imagesReady && window.__marker.state.source === 'local'", timeout=15000)
    kept = p.evaluate("() => window.__marker.state.tasks['T001'].xray.filter(Boolean).length")
    res.check(f"ครบ {len(m['items'])}/{len(m['items'])} งาน" in box and kept == 1 and p.is_hidden("#startScreen"),
              "L เปิดใหม่: กด ทำงานต่อ แล้วเปิดงานได้เลย ไม่ต้องเลือกไฟล์ จุดอยู่ครบ", box.replace("\n", " ")[:120])
    goto_task(p, 2)
    p.wait_for_function("() => window.__marker.state.imagesReady")
    res.check(p.evaluate("() => window.__marker.viewers.xray.W") == m["items"][2]["xray_size"][0],
              "L งานอื่นโหลดภาพจากในเครื่องได้ (ขนาดตรง manifest)", "")

    # 3) แผงดีบัก: สิทธิ์เก็บถาวร + พื้นที่ที่ใช้
    p.click("#btnDebug")
    p.wait_for_function("() => /พื้นที่ที่เว็บใช้ \\d+ MB/.test(document.getElementById('debugInfo').textContent)")
    dbg = p.text_content("#debugInfo") or ""
    p.click("#btnDebugClose")
    res.check("เก็บถาวร (persist)=" in dbg and "ภาพจาก: ในเครื่อง" in dbg, "L แผงดีบัก: แสดงสิทธิ์เก็บถาวร พื้นที่ที่ใช้ และที่มาของภาพ",
              dbg.split("\n")[0][:80])

    # 4) ภาพในเครื่องเสีย (เนื้อไฟล์ไม่ตรง SHA-256) -> ข้อความชัด + เลือกแพ็กเกจใหม่ -> เก็บไฟล์นั้นใหม่ จุดไม่หาย
    p.evaluate(IMG_DB_OP, ["corrupt", pkg, m["items"][1]["xray"]])
    p.evaluate("() => { window.__marker.showTask(1); }")
    title = wait_dialog(p)
    body = p.text_content("#dialogBody") or ""
    repick(p)
    p.wait_for_function("() => window.__marker.state.imagesReady && window.__marker.state.source === 'local'", timeout=15000)
    ls = local_state(p, pkg)
    kept = p.evaluate("() => window.__marker.state.tasks['T001'].xray.filter(Boolean).length")
    res.check("เลือกไฟล์แพ็กเกจอีกครั้ง" in title and "ไม่ครบหรือเสีย" in body and "ไม่หาย" in body and ls["complete"] and kept == 1,
              "L ภาพในเครื่องเสีย → บอกให้เลือกแพ็กเกจใหม่ → เก็บใหม่ครบ จุดไม่หาย", f"{title} · {ls}")

    # 5) ภาพหายบางไฟล์ -> หน้าแรกบอกว่าไม่ครบ ไม่มีปุ่ม ทำงานต่อ -> เลือกแพ็กเกจเดิม เก็บเฉพาะที่ขาด
    p.evaluate(IMG_DB_OP, ["delete", pkg, m["items"][3]["fluoro"]])
    p.reload()
    p.wait_for_selector("body[data-ready='1']")
    p.wait_for_selector("#localBox:not([hidden])")
    box = p.text_content("#localBox") or ""
    no_resume = not p.is_visible("#btnResume")
    p.evaluate("() => { window.__puts = 0; const o = IDBObjectStore.prototype.put; IDBObjectStore.prototype.put = function (v) { if (v && v.blob) window.__puts++; return o.apply(this, arguments); }; }")
    open_pkg(p)
    p.wait_for_function("() => window.__marker.state.source === 'local'", timeout=15000)
    puts = p.evaluate("() => window.__puts")
    res.check("ไม่ครบ" in box and f"ขาด 1 จาก {nfiles}" in box and no_resume and puts == 1 and local_state(p, pkg)["complete"],
              "L ภาพหายบางไฟล์ → หน้าแรกบอกชัด → เลือกแพ็กเกจเดิม เก็บเฉพาะไฟล์ที่ขาด", f"{box[:80]} puts={puts}")

    # 6) ภาพหายทั้งหมด (จำลองเบราว์เซอร์ลบ) แต่จุดยังอยู่ -> หน้าแรกบอก "ภาพในเครื่องหายไป"
    p.evaluate(DROP_IMG_DB)
    p.reload()
    p.wait_for_selector("body[data-ready='1']")
    box = p.text_content("#localBox") or ""
    saved = p.text_content("#savedList") or ""
    res.check("หายไป" in box and "จุดที่มาร์กไว้ไม่หาย" in box and pkg in saved and p.is_visible("#localBox"),
              "L ภาพหายทั้งหมด → หน้าแรกบอกให้เลือกแพ็กเกจใหม่ งานที่ทำไว้ยังอยู่", box[:80])
    open_pkg(p)
    p.wait_for_function("() => window.__marker.state.source === 'local'", timeout=15000)

    # 7) ลบภาพออกจากเครื่อง: เตือนสำรอง + ยืนยัน 2 ครั้ง · ลบเฉพาะภาพ จุดยังอยู่ · พื้นที่คืน
    flush(p)
    marks_before = idb_record(p, pkg)["tasks"]
    p.click("#btnOpen")
    p.wait_for_selector("#btnDeleteImages")
    p.click("#btnDeleteImages")
    t1 = wait_dialog(p)
    b1 = p.text_content("#dialogBody") or ""
    p.click("#btnDelCancel")
    still = local_state(p, pkg)["complete"]
    p.click("#btnDeleteImages")
    wait_dialog(p)
    p.click("#btnDelExportFirst")
    t_exp = wait_dialog(p)
    jname, _ = download(p, "#btnDlJson", "before_delete")
    p.click("#btnExportClose")
    wait_dialog(p)
    p.click("#btnDelNext")
    t2 = wait_dialog(p)
    p.click("#btnDelConfirm")
    p.wait_for_function("() => !window.ImageStore.flag() && document.getElementById('localBox').hidden", timeout=10000)
    left = p.evaluate(IMG_DB_COUNT)
    gone = left == 0
    marks_after = idb_record(p, pkg)["tasks"]
    u2 = p.evaluate(USAGE)
    res.check(t1.startswith("ลบภาพออกจากเครื่อง") and "จุดที่มาร์กไว้จะไม่ถูกลบ" in b1 and "สำรองล่าสุด" in b1 and still
              and "ส่งออก" in t_exp and jname.endswith(".json") and t2 == "ยืนยันอีกครั้ง",
              "L ปุ่มลบภาพ: เตือนให้สำรองก่อน (ส่งออกได้จากหน้าต่าง) + ยืนยัน 2 ครั้ง · ยกเลิกแล้วไม่ลบ", f"{t1} / {t2}")
    res.check(gone and tasks_equal(marks_after, marks_before),
              "L ลบภาพแล้ว: ไม่เหลือภาพในเครื่อง จุดที่มาร์กไว้ตรงเดิมทุกค่า", f"เหลือ {left} รายการ")
    res.check(u1 > u0 and u2 < u1, "L ลบภาพแล้ว พื้นที่ที่เว็บใช้ลดลง", f"ก่อนเก็บ {u0} · หลังเก็บ {u1} · หลังลบ {u2} ไบต์")
    p.close()
    p = env.page(c)
    saved = p.text_content("#savedList") or ""
    res.check(pkg in saved and "ทำแล้ว" in saved and not p.is_visible("#btnResume") and p.is_hidden("#localBox"),
              "L เปิดเว็บหลังลบภาพ: งานที่ทำไว้ยังแสดง ไม่มีปุ่ม ทำงานต่อ (ต้องเลือกแพ็กเกจ)", saved.replace("\n", " ")[:100])
    check_page_errors(p, res, "หน้าทดสอบภาพในเครื่อง")
    c.close()

    # 8) เก็บภาพไม่ได้ (พื้นที่เต็ม) -> ยังทำงานได้ด้วยไฟล์ที่เลือก + แจ้งเตือน
    c = env.ctx()
    p = env.page(c)
    p.evaluate("() => { window.ImageStore.save = () => Promise.reject(new DOMException('full', 'QuotaExceededError')); }")
    open_pkg(p)
    p.wait_for_function("() => window.__marker.state.imagesReady")
    msg = p.text_content("#toast") or ""
    res.check(p.evaluate("() => window.__marker.state.source") == "files" and "พื้นที่ในเครื่องไม่พอ" in msg,
              "L พื้นที่ไม่พอเก็บภาพ → แจ้งเตือน แล้วทำงานต่อด้วยไฟล์ที่เลือกได้", msg)
    c.close()


def test_update(env: Env):
    """ไอคอนบนหน้าจอโฮมได้เวอร์ชันใหม่เองโดยไม่ต้องลบไอคอน: เช็ก version.js → บันทึก → โหลดใหม่ → กลับเข้างานเดิม
    ข้อมูลในเครื่องไม่หาย · ไม่วนโหลดซ้ำถ้าเซิร์ฟเวอร์ยังส่งของเก่า · ทุกไฟล์ใน index.html มี ?v= ตรงกับ version.js"""
    res = env.res
    root = GEN.parents[1]
    ver = re.search(r"PELNAV_VERSION = '([^']+)'", (root / "marker" / "version.js").read_text(encoding="utf-8")).group(1)
    html = (root / "marker" / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="([\w.-]+\.(?:js|css))(\?v=[^"]*)?"', html)
    bad = [f + q for f, q in refs if q != f"?v={ver}"]
    res.check(refs and not bad, "U ทุกไฟล์ใน index.html มี ?v= ตรงกับ version.js (กันไฟล์เก่าปนไฟล์ใหม่)", str(bad))

    t = targets()
    c = env.ctx()
    p = env.page(c)
    res.check(p.evaluate("() => window.MARKER_CONFIG.APP_VERSION") == ver, "U เว็บอ่านเวอร์ชันจาก version.js", ver)
    open_pkg(p)
    p.wait_for_function("() => window.__marker.state.source === 'local'", timeout=15000)
    show_whole(p)
    inp = Input(p, c, "mouse")
    place_pairs(p, inp, [(t["T001_X.png"][0], t["T001_F.jpg"][0])])
    # เวอร์ชันเดิม -> ไม่โหลดใหม่
    same = p.evaluate("() => window.__marker.checkUpdate('test', true)")
    res.check(same is False and "?v=" not in p.url, "U เวอร์ชันบนเว็บเท่าเดิม → ไม่โหลดใหม่", p.url)

    # จำลองว่า push เวอร์ชันใหม่แล้ว (เซิร์ฟเวอร์ตอบ version.js ใหม่) — ไฟล์อื่นยังเป็นชุดเดิม
    p.route("**/version.js?check=*", lambda r: r.fulfill(status=200, content_type="application/javascript",
                                                          body="window.PELNAV_VERSION = '9.9.9';"))
    p.evaluate("() => { window.__marker.checkUpdate('test', true); }")
    p.wait_for_url("**/index.html?v=9.9.9", timeout=10000)
    p.wait_for_selector("body[data-ready='1']")
    p.wait_for_function("() => window.__marker.state.imagesReady && window.__marker.state.source === 'local'", timeout=15000)
    kept = p.evaluate("() => window.__marker.state.tasks['T001'].xray.filter(Boolean).length")
    res.check(kept == 1 and p.is_hidden("#startScreen"),
              "U มีเวอร์ชันใหม่ → บันทึก โหลดใหม่ แล้วกลับเข้างานเดิมเอง จุดอยู่ครบ (ไม่ต้องลบไอคอน)", p.url)
    # เซิร์ฟเวอร์ยังส่งไฟล์ชุดเดิม (9.9.9 > เวอร์ชันที่ได้) -> ต้องไม่วนโหลดซ้ำ
    again = p.evaluate("() => window.__marker.checkUpdate('test', true)")
    p.wait_for_timeout(1200)
    logged = p.evaluate("() => window.__marker.Debug.entries().some(e => e.msg.includes('ยังได้'))")
    res.check(again is False and p.url.endswith("?v=9.9.9") and logged,
              "U โหลดใหม่แล้วยังได้ของเก่า → ไม่วนโหลดซ้ำ (บันทึกในดีบัก)", p.url)
    # ระหว่างมีหน้าต่างถามค้าง -> ยังไม่โหลดใหม่
    p.evaluate("() => sessionStorage.removeItem('pelnavUpdateTried')")
    p.click("#btnUnmarkable")
    wait_dialog(p)
    held = p.evaluate("() => window.__marker.checkUpdate('test', true)")
    res.check(held is False and p.is_visible("#dialog"), "U มีหน้าต่างถามค้าง → ยังไม่โหลดใหม่ (รอจนปิดหน้าต่าง)", "")
    p.click("#btnReasonCancel")
    p.unroute("**/version.js?check=*")
    check_page_errors(p, res, "หน้าทดสอบอัปเดต")
    c.close()


def test_skip_jump(env: Env):
    """ข้ามไปก่อน (กันลืม) + ไปที่งาน"""
    res = env.res
    m = manifest()
    n = len(m["items"])
    c = env.ctx()
    p = env.page(c)
    open_pkg(p)
    idx = lambda: p.evaluate("() => window.__marker.state.index")       # noqa: E731
    st = lambda tid: p.evaluate("(id) => (window.__marker.state.tasks[id] || {}).status", tid)  # noqa: E731

    # 1) ข้าม T001, T002 -> นับว่ายังไม่เสร็จ แถบบนแสดงจำนวนที่ข้าม
    p.click("#btnSkip")
    p.wait_for_function("() => window.__marker.state.index === 1 && window.__marker.state.imagesReady")
    p.click("#btnSkip")
    p.wait_for_function("() => window.__marker.state.index === 2 && window.__marker.state.imagesReady")
    prog = p.text_content("#progress") or ""
    res.check(st("T001") == "skipped" and st("T002") == "skipped" and f"ทำแล้ว 0/{n}" in prog and "ข้ามไว้ 2" in prog,
              "K ข้ามไปก่อน: นับว่ายังไม่เสร็จ + แถบบนแสดง ทำแล้ว x/N · ข้ามไว้ y", prog)

    # 2) ทำงานที่ไม่ได้ข้ามครบ -> พากลับไปงานที่ข้ามอัตโนมัติ
    for i in range(2, n):
        p.click("#btnUnmarkable")
        choose_reason(p, "unclear")
        if i < n - 1:
            p.wait_for_function(f"() => window.__marker.state.index === {i + 1} && window.__marker.state.imagesReady")
    p.wait_for_function("() => window.__marker.state.index === 0 && window.__marker.state.imagesReady")
    msg = p.text_content("#toast") or ""
    res.check(idx() == 0 and "กลับไปงานที่ข้ามไว้" in msg and p.is_hidden("#dialog"),
              "K ทำงานที่ไม่ได้ข้ามครบ → พากลับไปงานที่ข้ามไว้งานแรกเอง (ไม่ต้องกดเลือก)", msg)

    # 3) กดข้ามซ้ำบนงานที่ข้ามไว้ -> ไปงานที่ข้ามถัดไป (วน) · งานที่ข้ามแล้วมาร์กเสร็จ -> ไปงานที่ข้ามที่เหลือ
    p.click("#btnSkip")
    p.wait_for_function("() => window.__marker.state.index === 1 && window.__marker.state.imagesReady")
    p.click("#btnSkip")
    p.wait_for_function("() => window.__marker.state.index === 0 && window.__marker.state.imagesReady")
    p.click("#btnUnmarkable")
    choose_reason(p, "unclear")
    p.wait_for_function("() => window.__marker.state.index === 1 && window.__marker.state.imagesReady")
    res.check(st("T001") == "unmarkable" and st("T002") == "skipped" and "ข้ามไว้ 1" in (p.text_content("#progress") or ""),
              "K งานที่ข้ามไว้: กดข้ามซ้ำวนไปงานที่ข้ามถัดไป · ทำเสร็จแล้วไปงานที่ข้ามที่เหลือ", p.text_content("#progress") or "")

    # 4) ไฟล์สำรอง JSON/CSV บันทึกสถานะ skipped
    p.click("#btnExport")
    wait_dialog(p)
    _, cpath = download(p, "#btnDlCsv", "skip")
    p.click("#btnExportClose")
    rows = [r for r in csv.DictReader(io.StringIO("\n".join(l for l in cpath.read_text(encoding="utf-8-sig").splitlines()
                                                          if not l.startswith("#"))))]
    csv_ok = any(r["task_id"] == "T002" and r["status"] == "skipped" for r in rows)

    # 5) จบงานขณะยังมีงานที่ข้าม -> เตือนพร้อมจำนวน · ยกเลิกได้ · จบไปก่อนได้
    p.click("#btnFinish")
    t1 = wait_dialog(p)
    p.click("#btnFinishCancel")
    still = p.is_hidden("#dialog") and p.is_hidden("#startScreen")
    p.click("#btnFinish")
    wait_dialog(p)
    p.click("#btnFinishAnyway")
    wait_dialog(p)
    _, jpath = download(p, "#btnDlJson", "skip")
    p.wait_for_selector("#startScreen:not([hidden])")
    data = json.loads(jpath.read_text(encoding="utf-8"))
    p.wait_for_function("() => (document.getElementById('savedList').textContent || '').includes('ข้ามไว้')")
    saved = p.text_content("#savedList") or ""
    res.check(t1 == "ยังมีงานที่ข้ามไว้ 1 งาน" and still, "K กด จบงาน ขณะมีงานที่ข้าม → เตือนพร้อมจำนวน (ยกเลิกได้)", t1)
    res.check(data["tasks"]["T002"]["status"] == "skipped" and csv_ok and "ข้ามไว้ 1 งาน" in saved,
              "K ไฟล์สำรอง JSON/CSV บันทึกสถานะ skipped + หน้าแรกแสดงจำนวนที่ข้าม", saved.replace("\n", " ")[:120])

    # 6) ไปที่งาน: พิมพ์เลข / T-เลข แล้วกระโดดได้ · เลขผิดแจ้งเตือน ไม่ย้าย
    p.click("#btnStartClose")
    p.fill("#jumpInput", "5")
    p.press("#jumpInput", "Enter")
    p.wait_for_function("() => window.__marker.state.index === 4 && window.__marker.state.imagesReady")
    p.fill("#jumpInput", "T003")
    p.click("#btnJump")
    p.wait_for_function("() => window.__marker.state.index === 2 && window.__marker.state.imagesReady")
    p.fill("#jumpInput", "99")
    p.press("#jumpInput", "Enter")
    p.wait_for_timeout(200)
    bad = p.text_content("#toast") or ""
    res.check(idx() == 2 and "ไม่มีงานเลข" in bad, "K ไปที่งาน: พิมพ์ 5 หรือ T003 แล้วไปได้ · เลขผิดแจ้งเตือนและไม่ย้าย", bad)
    check_page_errors(p, res, "หน้าทดสอบข้าม/ไปที่งาน")
    c.close()


SHARE_STUB = """
  window.__shared = [];
  Object.defineProperty(navigator, 'userAgent', { get: () => 'Mozilla/5.0 (iPad; CPU OS 26_4 like Mac OS X) AppleWebKit/605.1.15 Version/26.4 Mobile/15E148 Safari/604.1' });
  navigator.canShare = (d) => !!(d && d.files && d.files.length);
  navigator.share = async (d) => {
    const files = await Promise.all((d.files || []).map(async (f) => ({ name: f.name, type: f.type, text: await f.text() })));
    window.__shared.push({ keys: Object.keys(d).sort(), files });
  };
"""


def test_ios_share(env: Env):
    """iPad + https: ปุ่ม บันทึกไฟล์สำรองลงแอปไฟล์ ต้องส่งเฉพาะไฟล์ JSON 1 ไฟล์ (ไม่แนบข้อความ = ไม่มีไฟล์ข้อความแถม)"""
    res = env.res
    m = manifest()
    c = env.ctx(init=SHARE_STUB)
    p = env.page(c)
    open_pkg(p)
    p.click("#btnUnmarkable")
    choose_reason(p, "view_angle")
    p.wait_for_function("() => window.__marker.state.index === 1")
    p.click("#btnExport")
    wait_dialog(p)
    hint = p.text_content("#dialog") or ""
    p.click("#btnShareJson")
    p.wait_for_function("() => window.__shared.length === 1")
    sh = p.evaluate("() => window.__shared[0]")
    ok_json = len(sh["files"]) == 1 and sh["files"][0]["name"].endswith(".json") and json.loads(sh["files"][0]["text"])["format"] == "pelnav-marks"
    res.check(sh["keys"] == ["files"] and ok_json, "I แชร์บน iPad: ส่งเฉพาะไฟล์ JSON 1 ไฟล์ ไม่มี title/text", str(sh["keys"]) + " " + str([f["name"] for f in sh["files"]]))
    res.check("PelNav สำรอง" not in hint and "เลือกโฟลเดอร์" not in hint, "I คำแนะนำในหน้าต่างไม่พูดถึงโฟลเดอร์เฉพาะ", hint[:120])
    rec = idb_record(p, m["package_id"])
    res.check(rec["last_backup_at"] is not None, "I แชร์สำเร็จ = บันทึกเวลาสำรองล่าสุด", str(rec["last_backup_at"]))
    check_page_errors(p, res, "หน้าทดสอบแชร์")
    c.close()


MAC_INIT = """
  Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel' });
  Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0 });
"""
IPAD_INIT = """
  Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel' });
  Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 5 });
"""
TRACKPAD_JS = """
(a) => {
  const v = window.__marker.viewers.xray, c = v.canvas, r = c.getBoundingClientRect();
  const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  const snap = () => ({ s: v.s, tx: v.tx, ty: v.ty });
  const wheel = (o) => c.dispatchEvent(new WheelEvent('wheel', Object.assign({ clientX: cx, clientY: cy, bubbles: true, cancelable: true }, o)));
  const gest = (type, scale) => { const e = new Event(type, { bubbles: true, cancelable: true });
    Object.assign(e, { scale, clientX: cx, clientY: cy }); c.dispatchEvent(e); return e.defaultPrevented; };
  const out = {};
  out.s0 = snap();
  wheel({ deltaY: -40, ctrlKey: true });                 // Chrome: บีบสองนิ้ว = wheel + ctrl
  out.afterPinchWheel = snap();
  wheel({ deltaX: 12, deltaY: 30 });                     // เลื่อนสองนิ้ว
  out.afterScroll = snap();
  gest('gesturestart', 1);                               // Safari: gesture event
  gest('gesturechange', 1.5);
  out.afterGesture = snap();
  wheel({ deltaY: -40, ctrlKey: true });                 // Safari ส่ง wheel+ctrl ซ้อนระหว่าง gesture → ต้องไม่ซูมซ้ำ
  out.afterDupWheel = snap();
  gest('gestureend', 1.5);
  out.howTo = document.getElementById('howTo').textContent;
  return out;
}
"""


def test_mac_trackpad(env: Env):
    """MacBook: บีบสองนิ้ว (Chrome = wheel+ctrl, Safari = gesture event) = ซูม · เลื่อนสองนิ้ว = เลื่อนภาพ
    และเครื่องอื่นต้องทำงานแบบเดิม (Windows: ล้อ = ซูม · iPad: ไม่รับ gesture event ซ้อนกับ pointer)"""
    res = env.res
    c = env.ctx(init=MAC_INIT)
    p = env.page(c)
    open_pkg(p)
    o = p.evaluate(TRACKPAD_JS)
    s0, a, b, g, d = o["s0"], o["afterPinchWheel"], o["afterScroll"], o["afterGesture"], o["afterDupWheel"]
    res.check(a["s"] > s0["s"] * 1.2, "Mac: บีบสองนิ้วแบบ Chrome (wheel+ctrl) = ซูม", f"{s0['s']:.4f} -> {a['s']:.4f}")
    res.check(abs(b["s"] - a["s"]) < 1e-12 and abs(b["tx"] - (a["tx"] - 12)) < 1e-6 and abs(b["ty"] - (a["ty"] - 30)) < 1e-6,
              "Mac: เลื่อนสองนิ้ว = เลื่อนภาพ (ไม่ซูม)", f"s {a['s']:.4f}->{b['s']:.4f} t ({a['tx']:.1f},{a['ty']:.1f})->({b['tx']:.1f},{b['ty']:.1f})")
    res.check(abs(g["s"] / b["s"] - 1.5) < 1e-6, "Mac: บีบสองนิ้วแบบ Safari (gesture event) = ซูม ตามสัดส่วน", f"{b['s']:.4f} -> {g['s']:.4f}")
    res.check(abs(d["s"] - g["s"]) < 1e-12, "Mac Safari: wheel+ctrl ที่มาซ้อนระหว่าง gesture ไม่ซูมซ้ำ", f"{g['s']:.4f} -> {d['s']:.4f}")
    res.check("แทร็กแพด" in o["howTo"] and "บีบสองนิ้ว" in o["howTo"], "Mac: แถบวิธีใช้บอกท่าแทร็กแพด", o["howTo"])
    check_page_errors(p, res, "หน้าทดสอบ Mac")
    c.close()

    c = env.ctx()                                          # Windows (ค่าเดิม): ล้อเมาส์ = ซูม
    p = env.page(c)
    open_pkg(p)
    o = p.evaluate(TRACKPAD_JS)
    res.check(o["afterScroll"]["s"] < o["afterPinchWheel"]["s"] and abs(o["afterGesture"]["s"] / o["afterScroll"]["s"] - 1.5) < 1e-6
              and "ล้อ = ซูม" in o["howTo"], "Windows: ล้อเมาส์ = ซูมเหมือนเดิม", o["howTo"])
    c.close()

    c = env.ctx(init=IPAD_INIT)                            # iPad: ไม่รับ gesture event (ซูมผ่าน pointer อยู่แล้ว)
    p = env.page(c)
    open_pkg(p)
    o = p.evaluate(TRACKPAD_JS)
    res.check(abs(o["afterGesture"]["s"] - o["afterScroll"]["s"]) < 1e-12, "iPad: gesture event ไม่ทำให้ซูมซ้อน", "")
    c.close()


def test_private_mode(env: Env):
    res = env.res
    init = ("IDBFactory.prototype.open = function () { throw new DOMException('The user denied permission', 'SecurityError'); };")
    c = env.ctx(init=init)
    p = env.page(c)
    txt = p.text_content("#storageStatus") or ""
    disabled = p.evaluate("() => document.getElementById('inputFiles').disabled")
    res.check("ห้ามเริ่มงาน" in txt and disabled, "D โหมดส่วนตัว/บันทึกไม่ได้ (จำลอง) → เตือนและห้ามเริ่มงาน", txt[:120])
    c.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--channel", default="msedge")
    ap.add_argument("--only", default="", help="รันเฉพาะฟังก์ชันที่ชื่อมีคำนี้ (คั่นด้วย ,)")
    args = ap.parse_args()
    if not (GEN / "test_package_big" / "manifest.json").exists():
        sys.exit("ยังไม่มีภาพทดสอบ: รัน python tests/make_test_images.py ก่อน")
    if DL.exists():
        shutil.rmtree(DL)
    srv, base = start_server()
    res = Results()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=args.channel, headless=not args.headed)
        env = Env(browser, base, res)
        for fn in (test_box_and_realistic, test_navigation_quality, test_data_safety, test_forced_backup,
                   test_ios_resilience, test_local_images, test_skip_jump, test_update, test_ios_share, test_mac_trackpad, test_private_mode):
            if args.only and not any(k in fn.__name__ for k in args.only.split(",")):
                continue
            print(f"> {fn.__name__}", flush=True)
            try:
                fn(env)
            except Exception as e:  # ให้กลุ่มอื่นรันต่อได้
                res.check(False, f"! {fn.__name__} ล้มกลางคัน", repr(e)[:300])
            print(f"< {fn.__name__}", flush=True)
        browser.close()
        print("< browser closed", flush=True)
    # ปิดเซิร์ฟเวอร์ทดสอบแบบไม่รอค้าง (บางครั้ง shutdown() ค้างหลังเทสต์ที่จำลองการเลือกไฟล์ — ไม่เกี่ยวกับตัวเว็บ)
    import threading
    th = threading.Thread(target=srv.shutdown, daemon=True)
    th.start()
    th.join(3)
    print("< server closed", flush=True)
    # edge:// = หน้าต่างดาวน์โหลดของเบราว์เซอร์เอง (ไม่ได้มาจากหน้าเว็บ)
    outside = [(mth, u) for mth, u in env.requests
               if not (u.startswith(base) or u.startswith("blob:") or u.startswith("data:") or u.startswith("edge://"))]
    posts = [(mth, u) for mth, u in env.requests if mth != "GET"]
    res.check(not outside and not posts, "C ไม่มีคำขอเครือข่ายออกนอกเครื่อง/ไม่มีการส่งข้อมูล", f"{outside[:3]} {posts[:3]}")

    for ok, label, detail in res.rows:
        print(f"{'ผ่าน   ' if ok else 'ไม่ผ่าน'}  {label}" + ("" if ok else f"  {detail}"))
    n_ok = sum(1 for r in res.rows if r[0])
    print(f"\nผ่าน {n_ok} / {len(res.rows)} รายการ")
    sys.exit(1 if res.fails else 0)


if __name__ == "__main__":
    main()
