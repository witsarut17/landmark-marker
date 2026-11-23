"""คู่มือแพทย์แบบทีละขั้นพร้อมภาพ: ตรวจจุดของทีม (v1.3) — ถ่ายจากเซิร์ฟเวอร์ชั่วคราวในเครื่องด้วยภาพทดสอบเท่านั้น

    .venv\\Scripts\\python tools/make_review_guide.py      → manual_out/คู่มือแพทย์_ตรวจจุด.pdf

ขั้นตอน: แตะลิงก์ → หน้ารายการเคส → ทำต่อ → ดูจุดของทีม → ยืนยัน หรือลากแก้แล้วยืนยัน → มาร์กไม่ได้ → ครบเคสกลับรายการ → พักงาน
capture_review() ใช้ร่วมกับคู่มืออาจารย์ (tools/make_manual.py) เพื่อถ่ายหัวข้อ "ทีมมาร์กก่อน หมอตรวจ"
"""

from __future__ import annotations

import html
import json
import re
import shutil
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import make_manual as MM  # noqa: E402
from server import study as studymod  # noqa: E402
from server_fixture import H, TestServer  # noqa: E402
from test_coordinates import Input, to_page  # noqa: E402

PKG = "test_package"
PDF_NAME = "คู่มือแพทย์_ตรวจจุด.pdf"
SHOTS = MM.OUT / "review_shots"


def demo_study(pid: str) -> dict:
    return {"format": "pelnav-study", "version": 1, "package_id": pid, "seed": 1,
            "cases": [{"no": 1, "tasks": ["T006", "T002"], "marker": "team1"}, {"no": 2, "tasks": ["T001"], "marker": "team1"},
                      {"no": 3, "tasks": ["T003"], "marker": "team2"}, {"no": 4, "tasks": ["T004"], "marker": "team2"}],
            "extra": [{"no": 5, "task": "T003", "marker": "team1"}, {"no": 6, "task": "T006", "marker": "team2"}],
            "order": {"team1": [1, 5, 2], "team2": [3, 6, 4]}}


def _team_task(T, tid, n=4):
    pts = lambda key: [{"x": float(u), "y": float(v), "image_px_per_screen_px": 0.2, "at": "2026-11-23T00:00:00.000Z"}  # noqa: E731
                       for u, v in T[key][:n]] + [None] * (4 - n)
    xk = next(k for k in T if k.startswith(f"{tid}_X"))
    fk = next(k for k in T if k.startswith(f"{tid}_F"))
    return {"xray": pts(xk), "fluoro": pts(fk), "status": "done", "reason": None, "reason_text": None, "note": None,
            "started_at": "2026-11-23T00:00:00.000Z", "finished_at": "2026-11-23T00:02:00.000Z", "duration_ms": 120000,
            "updated_at": "2026-11-23T00:02:00.000Z"}


def setup_server():
    S = TestServer(packages=(PKG,))
    st = demo_study(S.pkg_ids[PKG])
    con = S.con()
    studymod.save_study(con, st)
    con.close()
    users = {n: S.add_user([], role="team", name=n) for n in ("team1", "team2")}
    return S, users


def put_team(S, users, name, tid, task):
    c = S.app.test_client()
    c.post("/api/login", json={"username": name, "password": users[name][1]}, headers=H)
    base = (c.get("/api/state").get_json().get("revs") or {}).get(tid, 0)     # งานที่เปิดในเบราว์เซอร์แล้วมี rev อยู่
    r = c.put(f"/api/tasks/{tid}", json={"task": task, "base_rev": base}, headers=H)
    assert r.status_code == 200, (tid, r.status_code)


def wait_task(p, label):
    p.wait_for_function("(l) => document.getElementById('taskLabel').textContent === l && window.__marker.state.imagesReady",
                        arg=label, timeout=30000)
    p.wait_for_timeout(300)


def capture_review(br, m: "MM.Manual", team: bool = True):
    """เพิ่มขั้นตอนลงใน m (หัวข้อปัจจุบัน): [ทีม] รายการเคส + ตัวช่วยคาดตำแหน่ง · [หมอ] รายการเคส ยืนยัน แก้ มาร์กไม่ได้ พักงาน"""
    S, users = setup_server()
    T = MM.targets(PKG)
    try:
        if team:
            cd = br.new_context(viewport=MM.DESKTOP, device_scale_factor=1.5, bypass_csp=True)
            p = cd.new_page()
            S.login(cd, "team1", users["team1"][1])
            p.goto(S.base + "/")
            p.wait_for_selector("#caseScreen:not([hidden])", timeout=30000)
            p.wait_for_timeout(300)
            m.shot(p, "หน้ารายการเคสของทีม",
                   "ปุ่ม **ทำต่อ** (หมายเลข 1) พาไปงานที่ยังไม่เสร็จ แตะเคส (หมายเลข 2) เพื่อทำหรือแก้ และเลือกดูเฉพาะเคสที่ยังไม่เสร็จได้ (หมายเลข 3)",
                   [MM.el("#btnContinue", 1), MM.el("#caseList", 2), MM.el("#caseScreen label.check", 3)])
            p.click("[data-case='1']")
            wait_task(p, "เคส 1 · คู่ 1/2")
            inp = Input(p, cd, "mouse")
            tx, tf = T["T006_X.png"], T["T006_F.jpg"]
            for i in range(3):
                MM.place(p, inp, "xray", *tx[i])
                MM.place(p, inp, "fluoro", *tf[i])
            MM.place(p, inp, "xray", *tx[3])
            g = p.evaluate("() => window.__marker.ghostFor('fluoro')")
            m.shot(p, "ตัวช่วยคาดตำแหน่งของทีม",
                   "วางครบ 3 คู่แล้ว เมื่อวางจุดที่ 4 บนภาพหนึ่ง อีกภาพจะแสดงวงประจาง ๆ ตรงตำแหน่งที่คาดไว้ (หมายเลข 1) ช่วยหาจุดคู่",
                   [MM.rect_around(p, "fluoro", g["x"], g["y"], r=34, n=1)])
            MM.place(p, inp, "fluoro", *tf[4])
            m.shot(p, "เตือนเมื่อจุดอาจไม่ตรงคู่",
                   "ถ้าจุดใดไม่สอดคล้องกับจุดอื่นเกินเกณฑ์ แถบด้านบนจะเตือน (หมายเลข 1) ให้ตรวจจุดนั้นอีกครั้ง ตัวช่วยนี้มีเฉพาะทีม",
                   [MM.el("#warnText", 1, at="below")])
            p.evaluate("() => window.__marker.undo()")
            MM.place(p, inp, "fluoro", *tf[3])
            p.click("#btnNext")
            wait_task(p, "เคส 1 · คู่ 2/2")
            p.evaluate("() => window.__marker.flushSave()")
            cd.close()
        else:
            put_team(S, users, "team1", "T006", _team_task(T, "T006"))
        put_team(S, users, "team1", "T001", _team_task(T, "T001"))
        put_team(S, users, "team1", "T002", _team_task(T, "T002"))
        put_team(S, users, "team2", "T003", _team_task(T, "T003"))
        put_team(S, users, "team2", "T004", _team_task(T, "T004"))

        # ----- หมอ (iPad)
        doc = S.add_user([PKG], name="doctor")
        ci = br.new_context(viewport=MM.IPAD, device_scale_factor=2, has_touch=True, user_agent=MM.IPAD_UA, bypass_csp=True)
        ci.add_init_script(MM.IPAD_INIT)
        q = ci.new_page()
        q.goto(S.link(doc[1]))
        q.wait_for_selector("#caseScreen:not([hidden])", timeout=30000)
        q.wait_for_timeout(300)
        m.shot(q, "แตะลิงก์ส่วนตัว แล้วจะเห็นรายการเคส",
               "ต่อ VPN แล้วแตะลิงก์ในข้อความ เว็บจะเปิดรายการเคส 1 ถึง 70 เอง ไม่ต้องพิมพ์อะไร กด **ทำต่อ** (หมายเลข 1)",
               [MM.el("#btnContinue", 1)], device="iPad")
        q.click("#btnContinue")
        wait_task(q, "เคส 1 · คู่ 1/2")
        m.shot(q, "ดูจุด 4 คู่ที่ทีมวางไว้",
               "จุดสีบนภาพเอกซเรย์และภาพฟลูคือจุดที่ทีมวางไว้ คู่สีเดียวกันคือจุดที่ตรงกัน แถบหมายเลข 1 บอกว่าต้องทำอะไร",
               [MM.el("#hintText", 1, at="below")], device="iPad")
        m.shot(q, "ถ้าจุดถูกต้อง กด ยืนยัน",
               "ถ้าทุกจุดตรงกันดี กด **ยืนยัน** (หมายเลข 1) เว็บบันทึกและไปคู่ถัดไปในเคสเดียวกันเอง",
               [MM.el("#btnNext", 1)], device="iPad")
        q.click("#btnNext")
        wait_task(q, "เคส 1 · คู่ 2/2")
        q.click("#btnFinger")
        old = q.evaluate("() => window.__marker.marks().xray[1]")
        ti = Input(q, ci, "touch")
        x, y = to_page(q, "xray", old["x"], old["y"])
        ti.down(x, y)
        q.wait_for_timeout(450)
        ti.move(x, y, x + 26, y + 10)
        q.wait_for_timeout(200)
        m.shot(q, "ถ้าจุดไม่ตรง กดค้างที่จุดแล้วลากแก้",
               "กดนิ้วหรือปากกาค้างที่จุด แว่นขยาย (หมายเลข 1) จะขึ้น ค่อย ๆ ลากให้กากบาทตรงตำแหน่งที่ถูก แล้วยกนิ้ว",
               [MM.loupe_item(q, "xray", 1)], device="iPad")
        ti.up(x + 26, y + 10)
        q.wait_for_timeout(200)
        q.click("#btnNext")
        q.wait_for_function("() => (document.getElementById('toast').textContent || '').includes('แก้')", timeout=5000)
        m.shot(q, "แก้แล้ว กด ยืนยัน",
               "หลังแก้ กด **ยืนยัน** เว็บบอกจำนวนจุดที่แก้ (หมายเลข 1) จุดเดิมของทีมยังเก็บไว้ ไม่ถูกเขียนทับ",
               [MM.el("#toast", 1)], device="iPad", keep_toast=True)
        q.wait_for_selector("#caseScreen:not([hidden])", timeout=10000)
        q.wait_for_timeout(300)
        m.shot(q, "ครบทุกคู่ในเคส กลับหน้ารายการเอง",
               "เคสที่ตรวจครบขึ้นว่า เสร็จ (หมายเลข 1) กด **ทำต่อ** เพื่อไปเคสถัดไป หรือแตะเคสเก่าเพื่อดูหรือแก้ได้",
               [MM.el("[data-case='1']", 1)], device="iPad")
        q.click("#btnContinue")
        wait_task(q, "เคส 2 · คู่ 1/1")
        q.click("#btnUnmarkable")
        MM.wait_dialog(q)
        m.shot(q, "ถ้าภาพนี้มาร์กไม่ได้",
               "กด **มาร์กไม่ได้** แล้วเลือกเหตุผล (หมายเลข 1) และกด **ยืนยัน** ถ้าจำเป็นต้องเพิ่มหรือลบจุด ใช้ปุ่ม **ลบจุด** หรือวางจุดใหม่ได้",
               [MM.el("#dialog .card", 1)], device="iPad")
        MM.choose_reason(q, "unclear")
        q.wait_for_selector("#caseScreen:not([hidden])", timeout=10000)
        q.click("#btnCasePause")
        MM.wait_dialog(q)
        m.shot(q, "เลิกทำ กด พักงาน",
               "กด **พักงาน** เมื่อขึ้นว่าบันทึกครบแล้วปิดเว็บได้เลย ครั้งหน้าแตะลิงก์เดิมแล้วกด **ทำต่อ**",
               [MM.el("#dialog .card", 1)], device="iPad")
        q.click("#btnPauseStay")
        ci.close()
    finally:
        S.stop()


GUIDE_CSS = """
.step img { max-height: 105mm; }
.lead { font-size: 18pt; }
"""


def build_html(m: "MM.Manual", version: str) -> str:
    parts = ['<div class="cover"><h1>คู่มือแพทย์<br>ตรวจจุดอ้างอิงที่ทีมวางไว้</h1>'
             f"<p>ทำตามทีละขั้น ใช้ได้ทั้ง iPad และคอมพิวเตอร์</p><p>เวอร์ชัน {html.escape(version)}</p></div>"]
    parts.append('<section class="sec"><h2>ก่อนเริ่ม</h2>'
                 '<p class="lead">ทีมวิจัยวางจุด 4 คู่ไว้ให้ทุกงานแล้ว แพทย์มีหน้าที่ตรวจ ถ้าถูกต้องกด ยืนยัน ถ้าไม่ตรงให้ลากแก้แล้วกด ยืนยัน</p>'
                 '<p class="lead">ต้องต่อ VPN ของมหาวิทยาลัยก่อนทุกครั้ง แบบเดียวกับตอนเปิด CVAT แล้วแตะลิงก์ส่วนตัวที่ทีมส่งให้ '
                 'ลิงก์นี้ห้ามส่งต่อ จุดที่ยืนยันบันทึกขึ้นเซิร์ฟเวอร์ทันที ไม่ต้องสำรองหรือส่งไฟล์</p>'
                 '<p class="lead">ภาพในคู่มือนี้เป็นภาพทดสอบที่สร้างขึ้น ไม่ใช่ภาพผู้ป่วย</p>')
    for b in m.blocks:
        if b[0] == "step":
            parts.append(MM.step_html(b))
    parts.append("</section>")
    return ('<!doctype html><html lang="th"><head><meta charset="utf-8"><title>คู่มือแพทย์ ตรวจจุดอ้างอิง</title>'
            f"<style>{MM.font_css()}\n{MM.CSS}\n{GUIDE_CSS}</style></head><body>" + "\n".join(parts) + "</body></html>")


def main():
    if not (MM.GEN / PKG / "manifest.json").exists():
        sys.exit("ยังไม่มีภาพทดสอบ: รัน python tests/make_test_images.py ก่อน")
    if not MM.gitignored(MM.OUT / "x.pdf"):
        sys.exit("หยุด: manual_out/ ต้องอยู่ใน .gitignore ก่อน")
    if SHOTS.exists():
        shutil.rmtree(SHOTS)
    SHOTS.mkdir(parents=True)
    MM.SHOTS = SHOTS                                    # Manual.shot เขียนลงโฟลเดอร์นี้
    m = MM.Manual()
    with sync_playwright() as pw:
        br = pw.chromium.launch(channel="msedge")
        capture_review(br, m, team=False)
        br.close()
    version = re.search(r"PELNAV_VERSION = '([^']+)'", (ROOT / "marker" / "version.js").read_text(encoding="utf-8")).group(1)
    page_html = build_html(m, version).replace('src="shots/', 'src="review_shots/')
    MM.check_text(page_html)
    src = MM.OUT / "review_guide.html"
    src.write_text(page_html, encoding="utf-8")
    pdf = MM.OUT / PDF_NAME
    with sync_playwright() as pw:
        br = pw.chromium.launch(channel="msedge")
        pg = br.new_page()
        pg.goto(src.as_uri())
        pg.wait_for_load_state("networkidle")
        pg.evaluate("() => document.fonts.ready")
        pg.emulate_media(media="print")
        pg.set_viewport_size({"width": 624, "height": 900})
        long_caps = pg.evaluate("""() => [...document.querySelectorAll('.step')].filter(s => {
            const c = s.querySelector('.cap'); if (!c) return false;
            return Math.round(c.getBoundingClientRect().height / parseFloat(getComputedStyle(c).lineHeight)) > 2;
          }).map(s => s.querySelector('h3').textContent)""")
        if long_caps:
            sys.exit(f"หยุด: คำอธิบายใต้ภาพยาวเกิน 2 บรรทัด {long_caps}")
        pg.pdf(path=str(pdf), format="A4", prefer_css_page_size=True, print_background=True)
        br.close()
    pages = len(re.findall(rb"/Type\s*/Page[^s]", pdf.read_bytes()))
    print(f"ภาพ {m.n_shot} ภาพ · PDF {pages} หน้า → {pdf}")


if __name__ == "__main__":
    main()
