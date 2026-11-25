"""ทดสอบหน้ามาร์กจุดในเบราว์เซอร์จริง (Edge ผ่าน Playwright) กับเซิร์ฟเวอร์จริง (ข้อมูลชั่วคราว ภาพทดสอบ)

รัน:  .venv\\Scripts\\python tests/test_workflow.py        (เพิ่ม --headed เพื่อดูหน้าจอ · --only ชื่อ เพื่อรันบางกลุ่ม)

กลุ่ม
  X  กรอบ: เปิดงานแล้วเอกซเรย์ซูมพอดีกรอบ (+15%), ปุ่ม ดูทั้งภาพ / กลับไปที่กรอบ, เปิด/ปิดกรอบ
  E  งานสมจริง T006: วางผ่านแว่นขยายในมุมมองเริ่มต้น (พอดีกรอบ) ทั้ง 4 คู่ คลาด ≤ 1 px
  N  ถัดไป/มาร์กไม่ได้/บันทึก 3 คู่ พร้อมเหตุผล, จุดไม่มีคู่ · Q เตือนจุดกระจุก/แนวเดียวกัน · T จับเวลา · P กลับสีไม่กระทบพิกัด
  S  เซิร์ฟเวอร์: เข้าสู่ระบบ, บันทึกทุกครั้งที่วาง, เปิดใหม่/อีกเครื่องเห็นงานเดิม, บัญชีทีม/ยังไม่กำหนดแพ็กเกจ
  O  เน็ตหลุด: คิวรอส่งในเครื่อง, ส่งเองเมื่อเน็ตกลับ, ปิดเว็บไปก่อนก็ไม่หาย, โหลดภาพไม่ได้ให้ลองใหม่, พักงานตอนเน็ตหลุด
  M  สองเครื่องบันทึกงานเดียวกัน, หมดเวลาเข้าสู่ระบบระหว่างทำ, พักงาน/ออกจากระบบ
  K  ข้ามไปก่อน + ไปที่งาน · U อัปเดตเวอร์ชันเอง · Mac แทร็กแพด · เก็บคิวในเครื่องไม่ได้ (โหมดส่วนตัว)
  C  ไม่มีคำขอเครือข่ายนอกเซิร์ฟเวอร์ของโครงการ / ไม่มี error ในหน้า
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_coordinates as TC  # noqa: E402
from test_coordinates import (GEN, ERR_INIT, Input, Results, goto_task, marks, place,  # noqa: E402
                              start_server, to_page, view, wait_loaded)

PKG = "test_package"


def server():
    return TC.SERVER


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
        return c.new_page()


def manifest(pkg=PKG):
    return json.loads((GEN / pkg / "manifest.json").read_text(encoding="utf-8"))


def targets(pkg=PKG):
    return json.loads((GEN / pkg / "targets.json").read_text(encoding="utf-8"))["targets"]


def open_pkg(page, pkg=PKG, user=None):
    """เข้าสู่ระบบ (บัญชีใหม่ งานว่าง ถ้าไม่ระบุ) แล้วเปิดแพ็กเกจจากเซิร์ฟเวอร์ · คืน (ชื่อ, รหัส)"""
    u = server().open(page, pkg, user)
    wait_loaded(page)
    return u


def wait_dialog(page):
    page.wait_for_selector("#dialog:not([hidden])", timeout=8000)
    return page.text_content("#dialogTitle") or ""


def choose_reason(page, code, text=None):
    wait_dialog(page)
    page.check(f"#dialog input[value='{code}']")
    if text:
        page.fill("#dialog .text-input", text)
    page.click("#btnReasonOk")


def flush(page):
    page.evaluate("() => window.__marker.flushSave()")


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


def tasks_equal(a, b):
    return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False)



# ---------------------------------------------------------------- S: เซิร์ฟเวอร์ (เข้าสู่ระบบ บันทึก เปิดใหม่ อีกเครื่อง)
def wait_saved(p, timeout=10000):
    p.wait_for_function("() => (document.getElementById('saveLabel').textContent || '').includes('บันทึกแล้ว')", timeout=timeout)


def test_server_save(env: Env):
    res = env.res
    S = server()
    t = targets()
    user = S.add_user([PKG])
    token = user[1]
    c = env.ctx()
    p = c.new_page()
    p.goto(S.url(PKG))
    p.wait_for_selector("#loginCard:not([hidden])")
    card = p.text_content("#loginCard") or ""
    res.check("ลิงก์ส่วนตัว" in card and p.locator("#loginCard input[type=password]").count() == 0,
              "S ยังไม่เข้าสู่ระบบ → บอกให้แตะลิงก์ส่วนตัว · ไม่มีช่องรหัสผ่าน", card[:80])
    p.goto(S.link("x" * 43, PKG))
    p.wait_for_function("() => (document.getElementById('loginErr').textContent || '').length > 0")
    err = p.text_content("#loginErr") or ""
    res.check("ใช้ไม่ได้" in err and "#t=" not in p.url, "S ลิงก์ผิด/หมดอายุ → แจ้งให้ขอลิงก์ใหม่ · ลบรหัสออกจากแถบที่อยู่", err)
    p.goto(S.link(token, PKG))
    wait_loaded(p)
    hist = p.evaluate("() => location.href")
    res.check(p.is_hidden("#startScreen") and token not in hist and "#" not in hist and token not in p.url,
              "S แตะลิงก์ส่วนตัว → เข้าสู่ระบบและเปิดงานเอง ไม่ต้องพิมพ์ · ลบรหัสออกจากแถบที่อยู่", hist)
    res.check(not any(token in u for _, u in env.requests), "S รหัสในลิงก์ไม่ถูกส่งไปใน URL ของคำขอใด ๆ (ส่งเฉพาะในเนื้อคำขอเข้าสู่ระบบ)", "")
    res.check(p.locator("#inputFiles").count() == 0 and p.locator("#btnExport").count() == 0 and p.locator("#btnOpen").count() == 0,
              "S ไม่มีปุ่มเลือกไฟล์ / ส่งออก / หน้าแรก ฝั่งหมอ", "")

    show_whole(p)
    inp = Input(p, c, "mouse")
    place_pairs(p, inp, list(zip(t["T001_X.png"][:2], t["T001_F.jpg"][:2])))
    wait_saved(p)
    rev, row = S.task_row(user[0], PKG, "T001")
    u, v = t["T001_X.png"][1]
    res.check(row and row["xray"][1] and abs(row["xray"][1]["x"] - u) <= 1 and abs(row["fluoro"][1]["y"] - t["T001_F.jpg"][1][1]) <= 1
              and rev >= 2, "S วางจุดแล้วบันทึกขึ้นเซิร์ฟเวอร์ทันที (ทุกครั้งที่วาง)", f"rev={rev} {row and row['xray'][:2]}")

    # หมายเหตุ + ไปงานที่ 3 แล้วเปิดใหม่ -> กลับมางานเดิม จุดและหมายเหตุอยู่ครบ (จากเซิร์ฟเวอร์)
    p.click("#btnNote")
    wait_dialog(p)
    p.fill("#noteInput", "จุด 2 ไม่แน่ใจ")
    p.click("#btnNoteOk")
    goto_task(p, 2)
    flush(p)
    p.reload()
    wait_loaded(p)
    st = p.evaluate("() => window.__marker.state")
    res.check(st["index"] == 2 and st["tasks"]["T001"]["xray"][1] is not None and st["tasks"]["T001"]["note"] == "จุด 2 ไม่แน่ใจ"
              and p.is_hidden("#startScreen"), "S เปิดใหม่ (ปิดแท็บ/รีเฟรช): ไม่ต้องใส่รหัสซ้ำ กลับงานเดิม จุดและหมายเหตุครบ", st["index"])

    # อีกเครื่อง (context ใหม่ = iPad อีกเครื่อง) บัญชีเดียวกัน -> เห็นงานเดียวกัน
    c2 = env.ctx({"width": 1180, "height": 820})
    p2 = c2.new_page()
    S.open(p2, PKG, user)
    wait_loaded(p2)
    t2 = p2.evaluate("() => window.__marker.state.tasks['T001']")
    res.check(tasks_equal(t2["xray"], st["tasks"]["T001"]["xray"]) and p2.evaluate("() => window.__marker.state.index") == 2,
              "S เปิดจากอีกเครื่องด้วยบัญชีเดียวกัน → เห็นงานและตำแหน่งงานเดียวกัน", "")
    c2.close()

    # บัญชีทีม / แพทย์ที่ยังไม่ได้กำหนดแพ็กเกจ
    for role, pk, expect, label in (("team", [PKG], "ทีมวิจัย", "บัญชีทีมเปิดหน้ามาร์ก → บอกให้ใช้หน้าทีม"),
                                    ("doctor", [], "ติดต่อทีม", "แพทย์ที่ยังไม่ได้กำหนดแพ็กเกจ → บอกให้ติดต่อทีม")):
        cu = env.ctx()
        pu = cu.new_page()
        uu = S.add_user(pk, role=role)
        S.login(cu, *uu)
        pu.goto(S.url())
        pu.wait_for_function("(e) => (document.getElementById('startMsg').textContent || '').includes(e)", arg=expect, timeout=8000)
        msg = pu.text_content("#startMsg") or ""
        res.check(expect in msg, f"S {label}", msg)
        cu.close()
    check_page_errors(p, res, "หน้าทดสอบเซิร์ฟเวอร์")
    c.close()


# ---------------------------------------------------------------- O: เน็ตหลุด
def outbox(p, user, pkg_id):
    return p.evaluate("(k) => window.Store.get(k).then(r => r ? Object.keys(r.tasks) : [])", f"outbox:{user}:{pkg_id}")


def test_offline(env: Env):
    res = env.res
    S = server()
    t = targets()
    pid = S.pkg_ids[PKG]
    c = env.ctx()
    p = c.new_page()
    user = S.open(p, PKG)
    wait_loaded(p)
    show_whole(p)
    inp = Input(p, c, "mouse")
    xt, ft = t["T001_X.png"], t["T001_F.jpg"]
    place_pairs(p, inp, [(xt[0], ft[0])])
    wait_saved(p)

    # เน็ตหลุด -> วางต่อได้ แถบบนบอกว่ายังไม่ได้ส่ง และคิวเก็บในเครื่อง
    c.set_offline(True)
    place_pairs(p, inp, [(xt[1], ft[1])])
    p.wait_for_function("() => (document.getElementById('saveLabel').textContent || '').includes('ยังไม่ได้ส่ง')", timeout=10000)
    lbl = p.text_content("#saveLabel") or ""
    ob = outbox(p, user[0], pid)
    srv_before = S.task_row(user[0], PKG, "T001")[1]
    res.check("ยังไม่ได้ส่ง 1 งาน" in lbl and ob == ["T001"] and srv_before["xray"][1] is None,
              "O เน็ตหลุด: วางจุดต่อได้ · แถบบนบอก ยังไม่ได้ส่ง · เก็บคิวไว้ในเครื่อง", f"{lbl} · คิว={ob}")
    # เน็ตกลับมา -> ส่งเอง
    c.set_offline(False)
    p.evaluate("() => window.dispatchEvent(new Event('online'))")
    wait_saved(p, 15000)
    srv_after = S.task_row(user[0], PKG, "T001")[1]
    res.check(srv_after["xray"][1] is not None and outbox(p, user[0], pid) == [],
              "O เน็ตกลับมา → ส่งงานที่ค้างขึ้นเซิร์ฟเวอร์เอง แล้วล้างคิวในเครื่อง", "")

    # เน็ตหลุดแล้วปิดเว็บไปเลย -> เปิดใหม่ตอนเน็ตกลับมา ส่งเอง
    c.set_offline(True)
    place_pairs(p, inp, [(xt[2], ft[2])])
    p.wait_for_function("() => (document.getElementById('saveLabel').textContent || '').includes('ยังไม่ได้ส่ง')", timeout=10000)
    p.close()
    c.set_offline(False)
    p = c.new_page()
    p.goto(S.url(PKG))
    wait_loaded(p)
    p.wait_for_function("() => (document.getElementById('saveLabel').textContent || '').includes('บันทึกแล้ว')", timeout=15000)
    srv3 = S.task_row(user[0], PKG, "T001")[1]
    res.check(srv3["xray"][2] is not None and p.evaluate("() => window.__marker.state.tasks['T001'].xray[2]") is not None,
              "O เน็ตหลุดแล้วปิดเว็บ → เปิดใหม่ งานที่ค้างถูกส่งขึ้นเซิร์ฟเวอร์ ไม่หาย", "")

    # โหลดภาพไม่ได้ตอนเน็ตหลุด -> ข้อความชัด + ลองใหม่ได้
    c.set_offline(True)
    p.evaluate("() => { window.__marker.showTask(4); }")
    title = wait_dialog(p)
    c.set_offline(False)
    p.click("#btnImgRetry")
    p.wait_for_function("() => window.__marker.state.index === 4 && window.__marker.state.imagesReady", timeout=15000)
    res.check("โหลดภาพไม่ได้" in title, "O โหลดภาพไม่ได้ (เน็ตหลุด) → บอกชัด + กด ลองใหม่ ได้", title)

    # พักงานขณะยังส่งไม่ได้ -> บอกว่างานเก็บในเครื่อง ยังส่งไม่ครบ
    c.set_offline(True)
    p.evaluate("() => { const t = window.__marker.task(); t.note = 'ตอนเน็ตหลุด'; t.updated_at = new Date().toISOString(); window.__marker.save(); }")
    p.click("#btnFinish")
    t_pause = wait_dialog(p)
    body = p.text_content("#dialogBody") or ""
    p.click("#btnPauseStay")
    c.set_offline(False)
    p.evaluate("() => window.dispatchEvent(new Event('online'))")
    wait_saved(p, 15000)
    res.check("ยังส่งไม่ครบ" in t_pause and "ไม่หาย" in body, "O กดพักงานตอนเน็ตหลุด → บอกว่ายังส่งไม่ครบ งานเก็บในเครื่องไม่หาย", t_pause)
    check_page_errors(p, res, "หน้าทดสอบเน็ตหลุด")
    c.close()


# ---------------------------------------------------------------- M: สองเครื่อง / หมดเวลาเข้าสู่ระบบ / พักงาน
def test_multi_device(env: Env):
    res = env.res
    S = server()
    t = targets()
    xt, ft = t["T001_X.png"], t["T001_F.jpg"]
    user = S.add_user([PKG])
    ca, cb = env.ctx(), env.ctx()
    pa, pb = ca.new_page(), cb.new_page()
    S.open(pa, PKG, user)
    S.open(pb, PKG, user)
    wait_loaded(pa)
    wait_loaded(pb)
    show_whole(pa)
    show_whole(pb)
    ia, ib = Input(pa, ca, "mouse"), Input(pb, cb, "mouse")
    place(pa, ia, "xray", *xt[0])                       # A บันทึก rev 1
    wait_saved(pa)
    place(pb, ib, "fluoro", *ft[0])                     # B ยังไม่เห็นของ A (rev 0) -> ชนกัน -> ของ B ใหม่กว่า -> ส่งทับ
    wait_saved(pb)
    rev, row = S.task_row(user[0], PKG, "T001")
    warn_b = pb.text_content("#toast") or ""
    con = S.con()
    n_ev = con.execute("SELECT COUNT(*) FROM task_events e JOIN users u ON u.id = e.user_id WHERE u.username = ? AND e.task_id = 'T001'",
                       (user[0],)).fetchone()[0]
    con.close()
    res.check(rev >= 2 and row["fluoro"][0] is not None and "อีกเครื่อง" in warn_b and n_ev >= 2,
              "M สองเครื่องบันทึกงานเดียวกัน → ยึดอันที่แก้ล่าสุด · เตือนเครื่องที่ส่งทับ · ฉบับก่อนหน้าอยู่ในประวัติ", f"rev={rev} toast={warn_b} events={n_ev}")

    # อีกเครื่องแก้ใหม่กว่า (จำลองด้วย updated_at ในอนาคต) -> เครื่องนี้ใช้ของเซิร์ฟเวอร์ และแจ้งให้รู้
    pb.evaluate("""async () => { const m = window.__marker, t = JSON.parse(JSON.stringify(m.state.tasks['T001']));
        t.note = 'จากอีกเครื่อง'; t.updated_at = '2999-01-01T00:00:00.000Z';
        await m.api('/api/tasks/T001?package=' + new URLSearchParams(location.search).get('package'),
          { method: 'PUT', body: JSON.stringify({ task: t, base_rev: m.sync.revs['T001'] }) }); }""")
    place(pa, ia, "fluoro", *ft[0])                     # เครื่อง A ยังไม่เห็นจุดฟลูของ B -> วางคู่ของจุด 1 -> ชนกัน
    pa.wait_for_function("() => window.__marker.state.tasks['T001'].note === 'จากอีกเครื่อง'", timeout=10000)
    msg = pa.text_content("#toast") or ""
    res.check("อีกเครื่อง" in msg, "M อีกเครื่องแก้ใหม่กว่า → ใช้ข้อมูลล่าสุดจากเซิร์ฟเวอร์และแจ้งให้รู้", msg)
    cb.close()

    # ทีมสร้างลิงก์ใหม่ (ลิงก์หลุด) ระหว่างหมอทำงาน -> หน้าแตะลิงก์ · งานที่ค้างไม่หาย · แตะลิงก์ใหม่ (แท็บเดิม) แล้วส่งต่อ
    new_tok = S.new_link(user[0])
    place(pa, ia, "xray", *xt[1])
    pa.wait_for_selector("#loginCard:not([hidden])", timeout=10000)
    lmsg = pa.text_content("#loginMsg") or ""
    pa.goto(S.link(user[1], PKG))                      # ลิงก์เก่า -> ใช้ไม่ได้ งานยังค้างในเครื่อง
    pa.wait_for_function("() => (document.getElementById('loginErr').textContent || '').includes('ใช้ไม่ได้')", timeout=8000)
    still = pa.evaluate("() => window.__marker.sync.pending.size")
    pa.goto(S.link(new_tok, PKG))                      # ลิงก์ใหม่ในแท็บเดิม (เปลี่ยนแค่ #) -> เข้าสู่ระบบต่อ ไม่โหลดหน้าใหม่
    wait_saved(pa, 15000)
    row2 = S.task_row(user[0], PKG, "T001")[1]
    local = pa.evaluate("() => window.__marker.state.tasks['T001']")
    placed = any(q and abs(q["x"] - xt[1][0]) <= 1 and abs(q["y"] - xt[1][1]) <= 1 for q in row2["xray"])
    same = all((q is None) == (r is None) and (q is None or (abs(q["x"] - r["x"]) < 1e-6 and abs(q["y"] - r["y"]) < 1e-6))
               for q, r in zip(row2["xray"], local["xray"]))
    res.check("แตะลิงก์" in lmsg and still >= 1 and placed and same and pa.is_hidden("#startScreen") and "#t=" not in pa.url,
              "M ลิงก์ถูกเปลี่ยนระหว่างทำ → ขึ้นหน้าแตะลิงก์ · ลิงก์เก่าใช้ไม่ได้ · แตะลิงก์ใหม่แล้วงานที่ค้างถูกส่งต่อ ไม่หาย",
              f"{lmsg} · ค้าง {still} · {row2['xray'][:2]}")

    # พักงาน -> บันทึกครบ · ออกจากระบบ -> กลับหน้าใส่รหัส
    pa.click("#btnFinish")
    title = wait_dialog(pa)
    body = pa.text_content("#dialogBody") or ""
    pa.click("#btnLogout")
    pa.wait_for_selector("#loginCard:not([hidden])", timeout=10000)
    me = pa.evaluate("() => fetch('/api/me').then(r => r.status)")
    res.check(title == "พักงานได้" and "บันทึกบนเซิร์ฟเวอร์ครบแล้ว" in body and "ไม่ต้องสำรอง" in body and me == 401,
              "M พักงาน → บอกว่าบันทึกครบ ไม่ต้องสำรอง · ออกจากระบบได้", title)
    # วางลิงก์ในช่อง (เมื่อแตะลิงก์แล้วเปิดในแอปอื่น เช่น ไอคอนที่แยกจาก Safari)
    pa.fill("#linkInput", "ข้อความ ไม่มีลิงก์")
    pa.click("#btnLink")
    bad = pa.text_content("#loginErr") or ""
    pa.fill("#linkInput", "  " + S.link(new_tok, PKG) + "  ")
    pa.click("#btnLink")
    wait_loaded(pa)
    res.check("ไม่พบรหัส" in bad and pa.is_hidden("#startScreen") and pa.input_value("#linkInput") == "",
              "M วางลิงก์ส่วนตัวในช่อง → เข้าสู่ระบบได้ · วางข้อความที่ไม่ใช่ลิงก์ → แจ้งชัด", bad)
    check_page_errors(pa, res, "หน้าทดสอบสองเครื่อง")
    ca.close()


def test_skip_jump(env: Env):
    """ข้ามไปก่อน (กันลืม) + ไปที่งาน"""
    res = env.res
    m = manifest()
    n = len(m["items"])
    c = env.ctx()
    p = env.page(c)
    user = open_pkg(p)
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

    # 4) เซิร์ฟเวอร์บันทึกสถานะ skipped ให้ทีมเห็น
    flush(p)
    srv_st = server().task_row(user[0], PKG, "T002")[1]["status"]

    # 5) พักงานขณะยังมีงานที่ข้าม -> เตือนพร้อมจำนวน · ยกเลิกได้ · พักไปก่อนได้ (บอกว่าบันทึกครบ)
    p.click("#btnFinish")
    t1 = wait_dialog(p)
    p.click("#btnFinishCancel")
    still = p.is_hidden("#dialog")
    p.click("#btnFinish")
    wait_dialog(p)
    p.click("#btnFinishAnyway")
    t2 = wait_dialog(p)
    body = p.text_content("#dialogBody") or ""
    p.click("#btnPauseStay")
    res.check(t1 == "ยังมีงานที่ข้ามไว้ 1 งาน" and still, "K กด พักงาน ขณะมีงานที่ข้าม → เตือนพร้อมจำนวน (ยกเลิกได้)", t1)
    res.check(srv_st == "skipped" and t2 == "พักงานได้" and "ข้ามไว้ 1 งาน" in body,
              "K เซิร์ฟเวอร์บันทึกสถานะ skipped · หน้าต่างพักงานแสดงจำนวนที่ข้าม", f"{srv_st} · {body[:80]}")

    # 6) ไปที่งาน: พิมพ์เลข / T-เลข แล้วกระโดดได้ · เลขผิดแจ้งเตือน ไม่ย้าย
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


def test_update(env: Env):
    """ไอคอนบนหน้าจอโฮมได้เวอร์ชันใหม่เองโดยไม่ต้องลบไอคอน: เช็ก version.js → บันทึก → โหลดใหม่ → กลับเข้างานเดิม
    งานไม่หาย · ไม่วนโหลดซ้ำถ้าเซิร์ฟเวอร์ยังส่งของเก่า · ทุกไฟล์ใน index.html มี ?v= ตรงกับ version.js · URL คง ?package="""
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
    open_pkg(p)
    res.check(p.evaluate("() => window.MARKER_CONFIG.APP_VERSION") == ver, "U เว็บอ่านเวอร์ชันจาก version.js", ver)
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
    p.wait_for_url(lambda u: "v=9.9.9" in u and "package=" in u, timeout=10000)
    p.wait_for_selector("body[data-ready='1']")
    p.wait_for_function("() => window.__marker.state.imagesReady", timeout=15000)
    kept = p.evaluate("() => window.__marker.state.tasks['T001'].xray.filter(Boolean).length")
    res.check(kept == 1 and p.is_hidden("#startScreen"),
              "U มีเวอร์ชันใหม่ → บันทึก โหลดใหม่ แล้วกลับเข้างานเดิมเอง จุดอยู่ครบ (ไม่ต้องลบไอคอน)", p.url)
    # เซิร์ฟเวอร์ยังส่งไฟล์ชุดเดิม (9.9.9 > เวอร์ชันที่ได้) -> ต้องไม่วนโหลดซ้ำ
    again = p.evaluate("() => window.__marker.checkUpdate('test', true)")
    p.wait_for_timeout(1200)
    logged = p.evaluate("() => window.__marker.Debug.entries().some(e => e.msg.includes('ยังได้'))")
    res.check(again is False and "v=9.9.9" in p.url and logged,
              "U โหลดใหม่แล้วยังได้ของเก่า → ไม่วนโหลดซ้ำ (บันทึกในดีบัก)", p.url)
    # ระหว่างมีหน้าต่างถามค้าง -> ยังไม่โหลดใหม่
    p.evaluate("() => sessionStorage.removeItem('pelnavUpdateTried')")
    p.click("#btnUnmarkable")
    wait_dialog(p)
    held = p.evaluate("() => window.__marker.checkUpdate('test', true)")
    res.check(held is False and p.is_visible("#dialog"), "U มีหน้าต่างถามค้าง → ยังไม่โหลดใหม่ (รอจนปิดหน้าต่าง)", "")
    p.click("#btnReasonCancel")

    # แตะลิงก์ส่วนตัวครั้งแรกพอดีกับที่มีเวอร์ชันใหม่ -> โหลดใหม่แล้วยังเข้าสู่ระบบด้วยลิงก์นั้นได้ (รหัสไม่หายระหว่างโหลดใหม่)
    S = server()
    cu = env.ctx()
    pu = cu.new_page()
    pu.route("**/version.js?check=*", lambda r: r.fulfill(status=200, content_type="application/javascript",
                                                           body="window.PELNAV_VERSION = '9.9.8';"))
    uu = S.add_user([PKG])
    pu.goto(S.link(uu[1], PKG))
    pu.wait_for_url(lambda u: "v=9.9.8" in u, timeout=10000)
    wait_loaded(pu)
    res.check(pu.is_hidden("#startScreen") and "#t=" not in pu.url,
              "U แตะลิงก์ครั้งแรกพอดีมีเวอร์ชันใหม่ → โหลดใหม่แล้วเข้าสู่ระบบด้วยลิงก์ได้ · ไม่มีรหัสค้างในแถบที่อยู่", pu.url)
    cu.close()
    p.unroute("**/version.js?check=*")
    check_page_errors(p, res, "หน้าทดสอบอัปเดต")
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
    """เบราว์เซอร์เก็บข้อมูลในเครื่องไม่ได้ (โหมดส่วนตัว จำลอง) -> เตือน แต่ยังทำงานและบันทึกขึ้นเซิร์ฟเวอร์ได้"""
    res = env.res
    init = ("IDBFactory.prototype.open = function () { throw new DOMException('The user denied permission', 'SecurityError'); };")
    c = env.ctx(init=init)
    p = env.page(c)
    user = server().open(p, PKG)
    p.wait_for_function("() => (document.getElementById('toast').textContent || '').includes('เก็บงานสำรองในเครื่องไม่ได้')", timeout=8000)
    wait_loaded(p)
    show_whole(p)
    t = targets()
    place(p, Input(p, c, "mouse"), "xray", *t["T001_X.png"][0])
    flush(p)
    row = server().task_row(user[0], PKG, "T001")[1]
    res.check(row and row["xray"][0] is not None, "D เก็บคิวในเครื่องไม่ได้ (จำลอง) → เตือน แต่ยังบันทึกขึ้นเซิร์ฟเวอร์ได้", "")
    c.close()


def lan_ip() -> str | None:
    """เลข IP ของเครื่องในเครือข่าย (ไม่ส่งข้อมูลออกไปจริง) · ไม่มีเครือข่าย -> None"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()
    return None if ip.startswith("127.") else ip


def test_lan_http(env: Env):
    """H: เปิดผ่าน http + เลข IP (ไม่ใช่ 127.0.0.1) แบบเดียวกับเครื่องแล็บ — เบราว์เซอร์ถือว่า "ไม่ปลอดภัย" (isSecureContext = false)
    ทุกอย่างต้องยังทำงาน · และเซิร์ฟเวอร์ที่ไม่อนุญาตเครือข่ายนั้นต้องปฏิเสธ"""
    res = env.res
    ip = lan_ip()
    if not ip:
        res.check(True, "H ข้าม: เครื่องนี้ไม่มีเลข IP เครือข่าย (ทดสอบ http ผ่าน IP ไม่ได้)", "")
        return
    from server_fixture import TestServer
    srv = TestServer(packages=("test_package",), host="0.0.0.0", networks=[f"{ip}/32", "127.0.0.0/8"])
    blocked = TestServer(packages=("test_package",), host="0.0.0.0", networks=["127.0.0.0/8"])
    try:
        base = f"http://{ip}:{srv.port}"
        user = srv.add_user(["test_package"])
        c = env.browser.new_context(viewport={"width": 1180, "height": 820})
        c.add_init_script(ERR_INIT)
        p = c.new_page()
        p.goto(srv.link(user[1], "test_package", base))
        wait_loaded(p)
        secure = p.evaluate("() => window.isSecureContext")
        show_whole(p)
        t = targets()
        place(p, Input(p, c, "mouse"), "xray", *t["T001_X.png"][0])
        flush(p)
        p.reload()
        wait_loaded(p)
        row = srv.task_row(user[0], "test_package", "T001")[1]
        st = p.evaluate("() => window.__marker.state.tasks['T001']")
        res.check(secure is False and row and row["xray"][0] is not None and st["xray"][0] is not None and p.is_hidden("#startScreen"),
                  "H http ผ่านเลข IP (แบบเครื่องแล็บ): แตะลิงก์ เข้าได้ บันทึกได้ เปิดใหม่ยังเข้าอยู่", f"secure={secure}")
        check_page_errors(p, res, "หน้า http ผ่าน IP")
        p.goto(f"http://{ip}:{blocked.port}/")
        body = p.text_content("body") or ""
        res.check("VPN" in body, "H เครื่องที่อยู่นอกเครือข่ายที่อนุญาต → เปิดหน้าเว็บไม่ได้ บอกให้ต่อ VPN", body[:80])
        c.close()
    finally:
        srv.stop()
        blocked.stop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--channel", default="msedge")
    ap.add_argument("--only", default="", help="รันเฉพาะฟังก์ชันที่ชื่อมีคำนี้ (คั่นด้วย ,)")
    args = ap.parse_args()
    if not (GEN / "test_package_big" / "manifest.json").exists():
        sys.exit("ยังไม่มีภาพทดสอบ: รัน python tests/make_test_images.py ก่อน")
    srv, base = start_server()
    res = Results()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=args.channel, headless=not args.headed)
        env = Env(browser, base, res)
        for fn in (test_box_and_realistic, test_navigation_quality, test_server_save, test_offline, test_multi_device,
                   test_skip_jump, test_update, test_mac_trackpad, test_private_mode, test_lan_http):
            if args.only and not any(k in fn.__name__ for k in args.only.split(",")):
                continue
            print(f"> {fn.__name__}", flush=True)
            try:
                fn(env)
            except Exception as e:  # ให้กลุ่มอื่นรันต่อได้
                res.check(False, f"! {fn.__name__} ล้มกลางคัน", repr(e)[:300])
            print(f"< {fn.__name__}", flush=True)
        browser.close()
    srv.shutdown()
    outside = [(mth, u) for mth, u in env.requests
               if not (u.startswith(base) or u.startswith("blob:") or u.startswith("data:") or u.startswith("edge://"))]
    writes = [(mth, u) for mth, u in env.requests if mth != "GET" and not u.startswith(base + "/api/")]
    res.check(not outside and not writes, "C ไม่มีคำขอเครือข่ายนอกเซิร์ฟเวอร์ของโครงการ · เขียนข้อมูลเฉพาะ /api",
              f"{outside[:3]} {writes[:3]}")

    for ok, label, detail in res.rows:
        print(f"{'ผ่าน   ' if ok else 'ไม่ผ่าน'}  {label}" + ("" if ok else f"  {detail}"))
    n_ok = sum(1 for r in res.rows if r[0])
    print(f"\nผ่าน {n_ok} / {len(res.rows)} รายการ")
    sys.exit(1 if res.fails else 0)


if __name__ == "__main__":
    main()
