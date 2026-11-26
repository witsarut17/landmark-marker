"""คู่มือแพทย์ (ตรวจจุดของทีม) เป็น Word (.docx แก้ได้) + PDF — ถ่ายภาพหน้าจอจากเว็บรุ่นปัจจุบันบนเซิร์ฟเวอร์ชั่วคราวในเครื่อง

    .venv\\Scripts\\python -X utf8 -B tools/make_doctor_guide.py                 # ภาพจริงชุด train (ปิดชื่อ/HN) → C:\\PelNav_private\\doctor_guide\\
    .venv\\Scripts\\python -X utf8 -B tools/make_doctor_guide.py --test-images   # ภาพทดสอบสังเคราะห์ → manual_out/doctor_guide_test/ (ใช้ตรวจหน้าตา)

ภาพจริงมาจาก manual_out/sample_package (แพ็กเกจตัวอย่างชุด train ที่ปิดชื่อ/HN แล้ว + จุดของทีมใน sample_marks.json)
ไม่ใช่ภาพชุดทดสอบ 70 เคส · ไฟล์ผลลัพธ์ทั้งหมดอยู่นอก git · ทีมต้องเปิดดูทุกภาพด้วยตาก่อนส่ง
ต้องมี: Microsoft Word (แปลงเป็น PDF และฝังฟอนต์) และฟอนต์ TH Sarabun New ในเครื่อง
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
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
from test_coordinates import Input, session, to_page  # noqa: E402

PRIVATE_OUT = Path(r"C:\PelNav_private\doctor_guide")
TEST_OUT = MM.OUT / "doctor_guide_test"
NAME = "คู่มือแพทย์_ตรวจจุดอ้างอิง"
FONT = "TH Sarabun New"
LINK_PLACEHOLDER = "[วางลิงก์ของหมอที่นี่]"
CONTACT_PLACEHOLDER = "[ชื่อผู้ประสานงาน]   โทร [เบอร์โทรศัพท์]"


# ---------------------------------------------------------------- แพ็กเกจสำหรับถ่ายภาพ
def build_package(work: Path, test_images: bool) -> dict:
    """แพ็กเกจเล็ก 6 งานจากภาพตัวอย่าง: ภาพปกติใช้ซ้ำหลายงาน (มีจุดจริงของทีม) + ภาพแปลก 1 งาน (ทีมระบุมาร์กไม่ได้)"""
    if test_images:
        src = MM.GEN / "test_package"
        T = MM.targets("test_package")
        normal, odd = "T001", "T003"
        pairs = list(zip(T["T001_X.png"][:4], T["T001_F.jpg"][:4]))
    else:
        src = MM.SAMPLE_PKG
        sm = MM.load_sample_marks(MM.SAMPLE_MARKS)
        normal = sm["normal_id"]
        odd = sm["flip_id"] or next(t for t in sm["index"] if t != normal)
        pairs = sm["normal"][:4]
    man = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    items = {it["task_id"]: it for it in man["items"]}
    pkg = work / "guide_package"
    if pkg.exists():
        shutil.rmtree(pkg)
    pkg.mkdir(parents=True)
    plan = [("T001", normal), ("T002", normal), ("T003", normal), ("T004", odd), ("T005", normal), ("T006", normal)]
    out_items = []
    for tid, s in plan:
        it = dict(items[s])
        for side in ("xray", "fluoro"):
            ext = Path(it[side]).suffix
            shutil.copyfile(src / it[side], pkg / f"{tid}_{side[0].upper()}{ext}")
            it[side] = f"{tid}_{side[0].upper()}{ext}"
        it["task_id"] = tid
        it["is_repeat_of"] = None
        out_items.append(it)
    (pkg / "manifest.json").write_text(json.dumps({"package_id": "pkg-doctor-guide", "items": out_items}, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    return {"pkg": pkg, "pairs": [((float(a[0]), float(a[1])), (float(b[0]), float(b[1]))) for a, b in pairs],
            "box": items[normal]["box_xyxy"]}


def team_task(pairs, status="done", reason=None, shift=None):
    def pt(p):
        return {"x": p[0], "y": p[1], "image_px_per_screen_px": 0.2, "at": "2026-11-23T00:00:00.000Z"}
    xr = [pt(a) for a, _ in pairs] + [None] * (4 - len(pairs))
    fl = [pt(b) for _, b in pairs] + [None] * (4 - len(pairs))
    if shift:
        k, dx, dy = shift
        xr[k] = pt((pairs[k][0][0] + dx, pairs[k][0][1] + dy))
    return {"xray": xr, "fluoro": fl, "status": status, "reason": reason, "reason_text": None, "note": None,
            "started_at": "2026-11-23T00:00:00.000Z", "finished_at": "2026-11-23T00:02:00.000Z", "duration_ms": 120000,
            "updated_at": "2026-11-23T00:02:00.000Z"}


def put_team(S, users, name, tid, task):
    c = S.app.test_client()
    c.post("/api/login", json={"username": name, "password": users[name][1]}, headers=H)
    base = (c.get("/api/state").get_json().get("revs") or {}).get(tid, 0)
    r = c.put(f"/api/tasks/{tid}", json={"task": task, "base_rev": base}, headers=H)
    assert r.status_code == 200, (tid, r.status_code)


# ---------------------------------------------------------------- ถ่ายภาพ
def wait_task(p, label):
    p.wait_for_function("(l) => document.getElementById('taskLabel').textContent === l && window.__marker.state.imagesReady",
                        arg=label, timeout=30000)
    p.wait_for_timeout(350)


CROP_JS = """(s) => { const r = document.querySelector(s).getBoundingClientRect(); const m = 22;
  const x = Math.max(0, r.left - m), y = Math.max(0, r.top - m);
  return {x, y, width: Math.min(innerWidth - x, r.width + 2 * m), height: Math.min(innerHeight - y, r.height + 2 * m)}; }"""


def shoot(page, path: Path, items=(), keep_toast=False, clip=None, crop=None):
    """crop = ตัวเลือก CSS ของกล่องที่จะตัดภาพให้เหลือเฉพาะกล่องนั้น (หน้ารายการเคส / กล่องข้อความ)"""
    if crop:
        clip = page.evaluate(CROP_JS, crop)
    if not keep_toast:
        page.evaluate("() => { const t = document.getElementById('toast'); if (t) t.hidden = true; }")
    page.evaluate(MM.ANNOTATE_JS, list(items))
    page.wait_for_timeout(80)
    page.screenshot(path=str(path), type="jpeg", quality=86, clip=clip)
    page.evaluate("() => document.getElementById('__ann')?.remove()")


def capture(pk: dict, shots: Path) -> dict:
    """ถ่าย 10 ภาพตามลำดับการใช้งานจริง คืน {ชื่อ: ไฟล์}"""
    S = TestServer(packages=())
    pid = S.register("guide", pk["pkg"])
    st = {"format": "pelnav-study", "version": 1, "package_id": pid, "seed": 1,
          "cases": [{"no": 1, "tasks": ["T001", "T002", "T003"], "marker": "team1"},
                    {"no": 2, "tasks": ["T004", "T005"], "marker": "team1"},
                    {"no": 3, "tasks": ["T006"], "marker": "team2"}],
          "extra": [], "order": {"team1": [1, 2], "team2": [3]}}
    con = S.con()
    studymod.save_study(con, st)
    con.close()
    users = {n: S.add_user([], role="team", name=n) for n in ("team1", "team2")}
    P = pk["pairs"]
    b = pk["box"]
    shift = (1, 0.07 * (b[2] - b[0]), 0.05 * (b[3] - b[1]))          # คู่ที่ 2 ของงาน G02 คลาดเพื่อสาธิตการลากแก้
    put_team(S, users, "team1", "T001", team_task(P))
    put_team(S, users, "team1", "T002", team_task(P, shift=shift))
    put_team(S, users, "team1", "T003", team_task([], status="skipped"))
    put_team(S, users, "team1", "T004", team_task([], status="unmarkable", reason="no_overlap"))
    put_team(S, users, "team1", "T005", team_task(P))
    put_team(S, users, "team2", "T006", team_task(P))
    doc = S.add_user([pid], name="doctor")
    out = {}
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(channel="msedge")
            ci = br.new_context(viewport=MM.IPAD, device_scale_factor=2, has_touch=True, user_agent=MM.IPAD_UA, bypass_csp=True)
            ci.add_init_script(MM.IPAD_INIT)
            q = ci.new_page()
            q.goto(S.link(doc[1]))
            q.wait_for_selector("#caseScreen:not([hidden])", timeout=30000)
            q.wait_for_timeout(400)

            def snap(key, items=(), **kw):
                f = shots / f"{len(out) + 1:02d}_{key}.jpg"
                shoot(q, f, items, **kw)
                out[key] = f

            snap("list", [MM.el("#btnContinue", 1), MM.el("[data-case='1']", 2), MM.el("#caseScreen label.check", 3)], crop="#caseScreen .card")
            q.click("#btnContinue")
            wait_task(q, "เคส 1 · คู่ 1/3")
            snap("check", [MM.rect_around(q, "xray", *P[0][0], r=24, n=1), MM.rect_around(q, "fluoro", *P[0][1], r=24, n=2),
                           MM.el("#btnNext", 3)])
            q.click("#btnNext")
            wait_task(q, "เคส 1 · คู่ 2/3")
            q.click("#btnFinger")
            ti = Input(q, ci, "touch")
            bad = (P[1][0][0] + shift[1], P[1][0][1] + shift[2])
            x, y = to_page(q, "xray", *bad)
            ti.down(x, y)
            q.wait_for_timeout(500)
            ses = session(q, "xray")
            x1, y1 = x + (P[1][0][0] - ses["x"]) * ses["sL"], y + (P[1][0][1] - ses["y"]) * ses["sL"]
            ti.move(x, y, x1, y1, steps=10)
            q.wait_for_timeout(250)
            snap("drag", [MM.loupe_item(q, "xray", 1)])
            ti.up(x1, y1)
            q.wait_for_timeout(250)
            q.click("#btnNext")
            q.wait_for_function("() => (document.getElementById('toast').textContent || '').includes('แก้')", timeout=5000)
            wait_task(q, "เคส 1 · คู่ 3/3")
            snap("edited", [MM.el("#toast", 1)], keep_toast=True)
            q.wait_for_timeout(2600)
            snap("own", [MM.el("#hintText", 1, at="below"), MM.el("#btnFinger", 2, at="below")])
            pen = Input(q, ci, "pen")                        # วางเองครบ 4 คู่ด้วย Apple Pencil
            q.evaluate("() => { for (const v of Object.values(window.__marker.viewers)) v.resetView(); }")
            q.wait_for_timeout(200)
            for a, f in P:
                MM.place(q, pen, "xray", *a)
                MM.place(q, pen, "fluoro", *f)
            q.wait_for_function("() => window.__marker.marks().xray.filter(Boolean).length === 4", timeout=5000)
            q.click("#btnNext")
            q.wait_for_selector("#caseScreen:not([hidden])", timeout=10000)
            q.wait_for_timeout(400)
            snap("status", [MM.el("[data-case='1']", 1), MM.el("[data-case='2']", 2)], crop="#caseScreen .card")
            q.click("#btnContinue")
            wait_task(q, "เคส 2 · คู่ 1/2")
            snap("team_unm", [MM.el("#hintText", 1, at="below"), MM.el("#btnUnmarkable", 2, at="below")])
            q.click("#btnUnmarkable")
            MM.wait_dialog(q)
            snap("reasons", [MM.el("#dialog .card", 1)], crop="#dialog .card")
            MM.choose_reason(q, "no_overlap")
            wait_task(q, "เคส 2 · คู่ 2/2")
            tb = q.evaluate("() => { const r = document.getElementById('topbar').getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height}; }")
            f = shots / f"{len(out) + 1:02d}_topbar.jpg"
            shoot(q, f, [MM.el("#pairNav", 1), MM.el("#btnPrev", 2, at="below"), MM.el("#btnNext", 3, at="below"),
                         MM.el("#btnSkip", 4, at="below"), MM.el("#btnUnmarkable", 5, at="below"), MM.el(".jump-box", 6),
                         MM.el("#btnCases", 7), MM.el("#btnFinish", 8)],
                  clip={"x": 0, "y": 0, "width": MM.IPAD["width"], "height": tb["y"] + tb["h"] + 38})
            out["topbar"] = f
            q.click("#btnFinish")
            MM.wait_dialog(q)
            snap("pause", [MM.el("#dialog .card", 1)], crop="#dialog .card")
            ci.close()
            br.close()
    finally:
        S.stop()
    return out


# ---------------------------------------------------------------- เนื้อหา (เรียงตามหัวข้อที่ทีมกำหนด)
def content(vpn: str = "ของมหาวิทยาลัย", skipped: int | None = None, team_unm: int | None = None) -> list:
    n_skip = f"**{skipped} คู่ภาพ**" if skipped is not None else "บางคู่ภาพ"
    n_unm = f"**{team_unm} คู่ภาพ**" if team_unm is not None else "บางคู่ภาพ"
    """("h1"|"h2"|"p"|"li"|"img"|"link"|"contact"|"table"|"small", ...) · **ตัวหนา**"""
    return [
        ("title", "คู่มือการตรวจจุดอ้างอิง สำหรับแพทย์"),
        ("p", "ทีมวิจัยวางจุดอ้างอิงไว้ภาพละ 4 คู่ คือจุดบนภาพเอกซเรย์และจุดตำแหน่งเดียวกันบนภาพฟลูออโรสโคป (ภาพฟลู) "
              "หน้าที่ของแพทย์คือ **ตรวจ** ว่าแต่ละคู่อยู่ตำแหน่งกายวิภาคเดียวกันหรือไม่ "
              "ถ้าถูกต้องกด **ยืนยัน** ถ้าไม่ตรงให้ลากแก้แล้วกด **ยืนยัน** ใช้ได้ทั้ง iPad และคอมพิวเตอร์ ไม่ต้องติดตั้งโปรแกรม"),
        ("h1", "1. ก่อนเริ่ม"),
        ("li", f"ต่อ **VPN {vpn}** ทุกครั้งก่อนเปิดเว็บ"),
        ("li", "แตะลิงก์ด้านล่าง **ครั้งเดียว** เว็บจะเข้าสู่ระบบให้เอง ไม่ต้องใช้รหัสผ่าน"),
        ("link", LINK_PLACEHOLDER),
        ("li", "ครั้งต่อไป ต่อ VPN แล้วเปิดลิงก์เดิมนี้ได้เลย · ลิงก์นี้เป็นของแพทย์เท่านั้น กรุณาอย่าส่งต่อ"),
        ("h1", "2. หน้ารายการเคส"),
        ("img", "list", "กด **ทำต่อ** (1) เพื่อไปคู่ถัดไปที่ยังไม่ได้ตรวจ แตะเคส (2) เพื่อเลือกเอง "
                        "ติ๊ก **ซ่อนเคสที่เสร็จแล้ว** (3) เพื่อดูเฉพาะเคสที่เหลือ"),
        ("li", "แต่ละเคสมีภาพ 1–3 คู่ สถานะของเคส: **ยังไม่เริ่ม** · **ทำแล้ว 1/3** · **มีงานข้าม** · **เสร็จ**"),
        ("img", "status", "เคสที่ตรวจครบขึ้นว่า **เสร็จ** (1) ต้องการย้อนดูหรือแก้เคสเก่า แตะเคสนั้นได้เสมอ (2) = เคสที่ยังไม่เริ่ม"),
        ("li", "ระหว่างตรวจ กดปุ่ม **☰ เคส** มุมซ้ายบน เพื่อกลับมาหน้ารายการเคส"),
        ("h1", "3. ตรวจจุด"),
        ("img", "check", "จุดเลข 1 บนภาพเอกซเรย์ (1) ต้องเป็นตำแหน่งเดียวกับจุดเลข 1 บนภาพฟลู (2) ตรวจให้ครบ 4 คู่ "
                         "ถ้าถูกต้องทุกคู่ กด **ยืนยัน** (3)"),
        ("li", "ซูม: iPad ใช้สองนิ้วถ่าง/หุบ คอมพิวเตอร์หมุนลูกกลิ้งเมาส์ · เลื่อนภาพ: ลากบนพื้นที่ว่างของภาพ · "
               "ปุ่ม **ดูทั้งภาพ** กลับมุมมองเดิม"),
        ("li", "กด **ยืนยัน** แล้วเว็บบันทึกทันทีและไปคู่ถัดไปในเคสเดียวกัน"),
        ("h1", "4. ขยับจุดที่ไม่ตรง"),
        ("img", "drag", "กดค้างบนจุดที่ไม่ตรงจนแว่นขยาย (1) ขึ้น ลากให้กากบาทตรงตำแหน่งที่ถูกต้อง แล้วปล่อย"),
        ("img", "edited", "กด **ยืนยัน** เว็บแจ้งจำนวนจุดที่แก้ (1) จุดเดิมของทีมยังเก็บไว้ ไม่ถูกเขียนทับ"),
        ("li", "iPad: ใช้ Apple Pencil กดค้างได้ทันที ถ้าใช้นิ้ว ให้กดปุ่ม **นิ้ววางจุด** ให้เป็น เปิด ก่อน · "
               "คอมพิวเตอร์: คลิกค้างแล้วลาก · แก้ผิด กด **↶** (ย้อน)"),
        ("h1", "5. งานที่ทีมไม่ได้วางจุด"),
        ("p", f"ในชุดนี้มี {n_skip} ที่ทีมข้ามไว้ ไม่มีจุดของทีม แพทย์ต้องวางจุดเองตามขั้นตอนด้านล่าง"),
        ("img", "own", "ถ้าแถบด้านบนขึ้นว่า **ไม่มีจุดของทีม** (1) ให้วางจุดเอง 4 คู่ ถ้าใช้นิ้วบน iPad เปิด **นิ้ววางจุด** (2) ก่อน"),
        ("li", "กดค้างที่ตำแหน่งจนแว่นขยายขึ้น เลื่อนให้กากบาทตรงจุด แล้วปล่อย · วางจุด 1 บนภาพใดก็ได้ "
               "แล้ววางจุด 1 บนอีกภาพให้ตรงตำแหน่งเดียวกัน ทำต่อจนครบ 4 คู่ แล้วกด **ยืนยัน**"),
        ("li", "แถบด้านบนบอกเสมอว่าต้องวางจุดเลขใดบนภาพใด · วางผิด ลากแก้ได้ หรือแตะจุดแล้วกด **ลบจุด** · "
               "หาได้เพียง 3 คู่ กด **ยืนยัน** แล้วเลือกเหตุผล"),
        ("h1", "6. มาร์กไม่ได้"),
        ("p", f"ในชุดนี้ทีมระบุว่ามาร์กไม่ได้ {n_unm} แพทย์ตรวจว่าเห็นด้วยหรือไม่ และใช้ปุ่มนี้กับภาพอื่นที่หาจุดไม่ได้จริง"),
        ("img", "team_unm", "ถ้าทีมระบุว่ามาร์กไม่ได้ แถบด้านบนแสดงเหตุผลของทีม (1) ถ้าเห็นด้วย กด **มาร์กไม่ได้** (2) "
                            "ถ้าไม่เห็นด้วย วางจุดเอง 4 คู่"),
        ("img", "reasons", "เลือกเหตุผล (1) แล้วกด **ยืนยัน** ใช้เมื่อหาจุดที่ตรงกันบนสองภาพไม่ได้จริง"),
        ("li", "เหตุผล: **ภาพไม่ชัด** · **ไม่มีบริเวณร่วมกัน** (สองภาพเห็นกระดูกคนละส่วน) · **มุมถ่ายต่างกันมาก** · **อื่น ๆ** (พิมพ์เหตุผล)"),
        ("h1", "7. ปุ่มบนแถบด้านบน"),
        ("img", "topbar", "ปุ่มที่ใช้ระหว่างตรวจ หมายเลขตรงกับตารางด้านล่าง"),
        ("table", [("1", "ปุ่มคู่ 1 2 3", "ไปคู่นั้นทันที · ✓ ตรวจแล้ว  × มาร์กไม่ได้  ↷ ข้ามไว้"),
                   ("2", "◀ ก่อนหน้า", "กลับไปคู่ก่อนหน้าในเคสเดียวกัน"),
                   ("3", "ยืนยัน ▶", "บันทึกแล้วไปคู่ถัดไป · คู่สุดท้ายกลับหน้ารายการเคส"),
                   ("4", "ข้าม", "ข้ามไว้ก่อน เคสจะขึ้นว่า มีงานข้าม แล้วกลับมาทำทีหลัง"),
                   ("5", "มาร์กไม่ได้", "ใช้เมื่อหาจุดที่ตรงกันไม่ได้ (หัวข้อ 6)"),
                   ("6", "ไปที่งาน", "พิมพ์เลขคู่ในเคส แล้วกด ไป"),
                   ("7", "☰ เคส", "กลับหน้ารายการเคส"),
                   ("8", "พักงาน", "หยุดทำ (หัวข้อ 8)")]),
        ("h1", "8. พักงาน และติดต่อทีมวิจัย"),
        ("img", "pause", "กด **พักงาน** เมื่อขึ้นว่าบันทึกครบแล้ว (1) ปิดเว็บได้เลย ครั้งหน้าต่อ VPN เปิดลิงก์เดิม แล้วกด **ทำต่อ**"),
        ("li", "เว็บบันทึกทุกครั้งที่กด ยืนยัน ไม่ต้องสำรองหรือส่งไฟล์ · ทำต่อจากเครื่องไหนก็ได้ แต่ไม่ควรเปิดพร้อมกันสองเครื่อง"),
        ("contact", CONTACT_PLACEHOLDER),
        ("small", "ภาพในคู่มือนี้เป็นภาพตัวอย่างที่ปิดชื่อและ HN แล้ว"),
    ]


# ---------------------------------------------------------------- Word
def zwsp(text: str) -> str:
    """ใส่ zero-width space ระหว่างคำไทย ให้ Word ตัดบรรทัดถูก (ข้อความอังกฤษ/ตัวเลขไม่แตะ)"""
    from pythainlp.tokenize import word_tokenize
    return re.sub(r"[\u0E00-\u0E7F]+", lambda m: "\u200b".join(word_tokenize(m.group(0), engine="newmm", keep_whitespace=True)), text)


def build_docx(path: Path, shots: dict, test_images: bool, vpn: str, skipped=None, team_unm=None):
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    d = Document()
    sec = d.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2)
    sec.top_margin, sec.bottom_margin = Cm(1.6), Cm(1.5)
    usable = 21 - 4

    def cs_props(rpr, size=None, bold=None):
        """ภาษาไทยเป็น complex script: Word ใช้ฟอนต์ w:cs ขนาด w:szCs และตัวหนา w:bCs — ใส่ตามลำดับ schema"""
        fonts = rpr.get_or_add_rFonts()
        for k in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            fonts.set(qn(k), FONT)
        for k in ("w:asciiTheme", "w:hAnsiTheme", "w:cstheme", "w:eastAsiaTheme"):
            if fonts.get(qn(k)) is not None:
                del fonts.attrib[qn(k)]
        if bold:
            rpr.get_or_add_bCs()
        if size:
            e = rpr.find(qn("w:szCs"))
            if e is None:
                e = OxmlElement("w:szCs")
                rpr.insert_element_before(e, "w:highlight", "w:u", "w:effect", "w:bdr", "w:shd", "w:fitText", "w:vertAlign",
                                          "w:rtl", "w:cs", "w:em", "w:lang", "w:eastAsianLayout", "w:specVanish", "w:oMath")
            e.set(qn("w:val"), str(int(size * 2)))
        lang = rpr.find(qn("w:lang"))
        if lang is None:
            lang = OxmlElement("w:lang")
            rpr.insert_element_before(lang, "w:eastAsianLayout", "w:specVanish", "w:oMath")
        lang.set(qn("w:bidi"), "th-TH")

    def set_font(style, size, bold=None):
        f = style.font
        f.name = FONT
        f.size = Pt(size)
        if bold is not None:
            f.bold = bold
        f.color.rgb = RGBColor(0, 0, 0)
        cs_props(style.element.get_or_add_rPr(), size, bold)

    styles = d.styles
    set_font(styles["Normal"], 16)
    pf = styles["Normal"].paragraph_format
    pf.space_before, pf.space_after, pf.line_spacing = Pt(0), Pt(2), 1.0
    for name, size in (("Title", 26), ("Heading 1", 19)):
        s = styles[name]
        set_font(s, size, bold=True)
        s.paragraph_format.space_before = Pt(8 if name == "Heading 1" else 0)
        s.paragraph_format.space_after = Pt(2)
        s.paragraph_format.keep_with_next = True
        s.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    t_el = styles["Title"].element.get_or_add_pPr()
    for b in t_el.findall(qn("w:pBdr")):
        t_el.remove(b)
    cap = styles.add_style("GuideCaption", 1)
    cap.base_style = styles["Normal"]
    set_font(cap, 15)
    cap.paragraph_format.space_after = Pt(6)
    lst = styles["List Bullet"]
    set_font(lst, 16)
    lst.paragraph_format.space_after = Pt(1)

    def runs(par, text, size=None, bold_all=False):
        for i, part in enumerate(re.split(r"\*\*", text)):
            if not part:
                continue
            r = par.add_run(zwsp(part))
            bold = bold_all or i % 2 == 1
            if bold:
                r.bold = True
            if size:
                r.font.size = Pt(size)
            if bold or size:
                cs_props(r._element.get_or_add_rPr(), size, bold)
        return par

    def borders(cell, sz=8):
        tcPr = cell._element.get_or_add_tcPr()
        b = OxmlElement("w:tcBorders")
        for side in ("top", "left", "bottom", "right"):
            e = OxmlElement(f"w:{side}")
            e.set(qn("w:val"), "single")
            e.set(qn("w:sz"), str(sz))
            e.set(qn("w:color"), "000000")
            b.append(e)
        tcPr.append(b)

    def boxed(text, size):
        t = d.add_table(rows=1, cols=1)
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        c = t.cell(0, 0)
        c.width = Cm(usable)
        borders(c, 18)
        p = c.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(6)
        runs(p, text, size=size, bold_all=True)
        d.add_paragraph().paragraph_format.space_after = Pt(0)

    items = content(vpn, skipped, team_unm)
    for k, b in enumerate(items):
        kind = b[0]
        before_img = k + 1 < len(items) and items[k + 1][0] == "img"
        if kind == "title":
            d.add_paragraph(zwsp(b[1]), style="Title")
        elif kind == "h1":
            d.add_paragraph(zwsp(b[1]), style="Heading 1")
        elif kind == "p":
            runs(d.add_paragraph(), b[1]).paragraph_format.keep_with_next = before_img
        elif kind == "li":
            runs(d.add_paragraph(style="List Bullet"), b[1])
        elif kind == "small":
            p = runs(d.add_paragraph(), b[1], size=13)
            p.paragraph_format.space_before = Pt(6)
        elif kind == "link":
            boxed(b[1], 22)
        elif kind == "contact":
            p = runs(d.add_paragraph(), "**ติดปัญหา ติดต่อทีมวิจัย:**")
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.keep_with_next = True
            boxed(b[1], 18)
        elif kind == "img":
            f = shots[b[1]]
            p = d.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.keep_with_next = True
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(1)
            width = Cm({"topbar": usable, "list": 7.5, "status": 7.5, "reasons": 6.0, "pause": 7.4}.get(b[1], 9.0))
            p.add_run().add_picture(str(f), width=width)
            runs(d.add_paragraph(style="GuideCaption"), b[2])
        elif kind == "table":
            t = d.add_table(rows=1, cols=3)
            t.alignment = WD_TABLE_ALIGNMENT.CENTER
            t.autofit = False
            for gc, w in zip(t._tbl.tblGrid.gridCol_lst, (1.0, 3.4, usable - 4.4)):
                gc.w = Cm(w)
            hdr = ("ที่", "ปุ่ม", "ใช้ทำอะไร")
            for i, h in enumerate(hdr):
                runs(t.rows[0].cells[i].paragraphs[0], h, size=15, bold_all=True)
            for row in b[1]:
                cells = t.add_row().cells
                for i, v in enumerate(row):
                    runs(cells[i].paragraphs[0], v, size=15, bold_all=(i == 1))
            for k, r in enumerate(t.rows):
                trPr = r._tr.get_or_add_trPr()
                trPr.append(OxmlElement("w:cantSplit"))
                for i, w in enumerate((1.0, 3.4, usable - 4.4)):
                    r.cells[i].width = Cm(w)
                    borders(r.cells[i], 4)
                    pf2 = r.cells[i].paragraphs[0].paragraph_format
                    pf2.space_after = Pt(0)
                    pf2.keep_with_next = k < len(t.rows) - 1      # ตารางไม่แยกหน้า
            d.add_paragraph().paragraph_format.space_after = Pt(0)
    core = d.core_properties
    core.title = "คู่มือการตรวจจุดอ้างอิง สำหรับแพทย์"
    core.author = "ทีมวิจัย PelNavPlan"
    core.comments = "ภาพทดสอบสังเคราะห์" if test_images else ""
    d.save(str(path))


WORD_PS = r"""
$ErrorActionPreference = 'Stop'
$w = New-Object -ComObject Word.Application
$w.Visible = $false
try {
  $d = $w.Documents.Open($args[0])
  $d.EmbedTrueTypeFonts = $true
  $d.SaveSubsetFonts = $false
  $d.SaveAs2($args[0], 16)
  $d.ExportAsFixedFormat($args[1], 17)
  $pages = $d.ComputeStatistics(2)
  $caps = @()
  foreach ($p in $d.Paragraphs) {
    if ($p.Style.NameLocal -eq 'GuideCaption') {
      $r = $p.Range
      $a = $r.Characters.First.Information(10); $b = $r.Characters.Last.Information(10)
      $caps += [int]($b - $a + 1)
    }
  }
  $fonts = @()
  foreach ($f in $d.Content.Font.Name) { $fonts += $f }
  $d.Close(0)
  @{ pages = $pages; caption_lines = $caps; font = $fonts } | ConvertTo-Json -Compress
} finally { $w.Quit() }
"""


def word_finish(docx: Path, pdf: Path, work: Path) -> dict:
    ps = work / "word_export.ps1"
    ps.write_text("\ufeff" + WORD_PS, encoding="utf-8")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps), str(docx), str(pdf)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    if r.returncode != 0:
        sys.exit(f"Word แปลงไฟล์ไม่สำเร็จ: {r.stderr[-600:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--test-images", action="store_true", help="ใช้ภาพทดสอบสังเคราะห์ (ตรวจหน้าตา) → manual_out/doctor_guide_test/")
    ap.add_argument("--skipped", type=int, help="จำนวนคู่ภาพที่ทีมข้ามไว้ (จาก tools/check_team_marks.py) ไม่ใส่ = บางคู่ภาพ")
    ap.add_argument("--team-unmarkable", type=int, help="จำนวนคู่ภาพที่ทีมระบุมาร์กไม่ได้")
    ap.add_argument("--vpn", default="ของมหาวิทยาลัย", help="ชื่อ VPN ที่แสดงในคู่มือ (ใส่ตอนรัน ไม่เก็บชื่อหน่วยงานใน repo)")
    a = ap.parse_args()
    out = TEST_OUT if a.test_images else PRIVATE_OUT
    if a.test_images and not MM.gitignored(TEST_OUT / "x.pdf"):
        sys.exit("หยุด: manual_out/ ต้องอยู่ใน .gitignore")
    if not a.test_images and str(out).lower().startswith(str(ROOT).lower()):
        sys.exit("หยุด: ภาพจริงต้องอยู่นอกโปรเจกต์")
    work, shots = out / "work", out / "shots"
    for d in (work, shots):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
    pk = build_package(work, a.test_images)
    files = capture(pk, shots)
    docx, pdf = out / f"{NAME}.docx", out / f"{NAME}.pdf"
    build_docx(docx, files, a.test_images, a.vpn, a.skipped, a.team_unmarkable)
    info = word_finish(docx, pdf, work)
    shutil.rmtree(work)
    long_caps = [i + 1 for i, n in enumerate(info["caption_lines"]) if n > 2]
    print(f"ภาพ {len(files)} ภาพ · {info['pages']} หน้า · ฟอนต์ {info['font']} · คำอธิบายใต้ภาพยาวเกิน 2 บรรทัด: {long_caps or 'ไม่มี'}")
    print(f"→ {docx}\n→ {pdf}\n→ ภาพหน้าจอ {shots}")


if __name__ == "__main__":
    main()
