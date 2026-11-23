"""ทดสอบการศึกษาแบบ "ทีมมาร์กก่อน หมอตรวจ" (v1.3) ด้วยภาพทดสอบสังเคราะห์ — ไม่แตะข้อมูลจริง

    .venv\\Scripts\\python -X utf8 -B tests/test_study.py

V = นิยามการศึกษา/มุมมอง/สิทธิ์ (เซิร์ฟเวอร์) · R = จุดของทีมที่หมอเห็น + สถานะการตรวจ + ส่งออก · X = ย้ายจุดของทีม (export/import)
L = หน้ารายการเคส (เบราว์เซอร์) · A = ตัวช่วยของทีม · D = หมอตรวจ · T = หน้าทีม
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import csv
import io
import json
import math
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import manage  # noqa: E402
from server import study as studymod  # noqa: E402
from server_fixture import H, TestServer  # noqa: E402
from test_coordinates import ERR_INIT, GEN, Input, marks, place, session, to_page  # noqa: E402

rows: list[tuple[bool, str, str]] = []
PKG = "test_package"


def check(ok, label, detail=""):
    rows.append((bool(ok), label, str(detail)))


def study_for(pid: str) -> dict:
    return {"format": "pelnav-study", "version": 1, "package_id": pid, "seed": 1,
            "cases": [{"no": 1, "tasks": ["T001", "T002"], "marker": "team1"}, {"no": 2, "tasks": ["T006"], "marker": "team1"},
                      {"no": 3, "tasks": ["T003"], "marker": "team2"}, {"no": 4, "tasks": ["T004"], "marker": "team2"}],
            "extra": [{"no": 5, "task": "T003", "marker": "team1"}, {"no": 6, "task": "T006", "marker": "team2"}],
            "order": {"team1": [1, 5, 2], "team2": [3, 6, 4]}}


def targets():
    return json.loads((GEN / PKG / "targets.json").read_text(encoding="utf-8"))["targets"]


def manifest():
    return json.loads((GEN / PKG / "manifest.json").read_text(encoding="utf-8"))


def pt(x, y):
    return {"x": float(x), "y": float(y), "image_px_per_screen_px": 0.2, "at": "2026-11-23T00:00:00.000Z"}


def task_with(pairs, status="done", reason=None):
    xs = [pt(*p[0]) for p in pairs] + [None] * (4 - len(pairs))
    fs = [pt(*p[1]) for p in pairs] + [None] * (4 - len(pairs))
    return {"xray": xs, "fluoro": fs, "status": status, "reason": reason, "reason_text": None, "note": None,
            "started_at": "2026-11-23T00:00:00.000Z", "finished_at": "2026-11-23T00:01:00.000Z", "duration_ms": 60000,
            "updated_at": "2026-11-23T00:01:00.000Z"}


def setup(S: TestServer):
    st = study_for(S.pkg_ids[PKG])
    con = S.con()
    studymod.validate_study(st, manifest())
    studymod.save_study(con, st)
    con.close()
    users = {n: S.add_user([], role="team", name=n) for n in ("team1", "team2")}
    return st, users


def client_login(S, name, secret):
    c = S.app.test_client()
    if S.role_of(name) == "doctor":
        r = c.post("/api/link-login", json={"token": secret}, headers=H)
    else:
        r = c.post("/api/login", json={"username": name, "password": secret}, headers=H)
    assert r.status_code == 200, (name, r.status_code)
    return c


def put(c, tid, task, base=0):
    return c.put(f"/api/tasks/{tid}", json={"task": task, "base_rev": base}, headers=H)


# ---------------------------------------------------------------- V / R / X (เซิร์ฟเวอร์)
def server_part():
    S = TestServer(packages=(PKG,))
    try:
        st, users = setup(S)
        m = manifest()
        bad = []
        for label, mut in (("งานซ้ำ", lambda s: s["cases"][0]["tasks"].append("T005")),
                           ("งานที่ไม่มี", lambda s: s["cases"][0]["tasks"].append("T099")),
                           ("งานอยู่ 2 เคส", lambda s: s["cases"][1]["tasks"].append("T001")),
                           ("เลขเคสขาด", lambda s: s["cases"][3].update(no=9)),
                           ("คู่พิเศษเป็นเคสของตัวเอง", lambda s: s["extra"][0].update(task="T001")),
                           ("แพ็กเกจผิด", lambda s: s.update(package_id="pkg-x")),
                           ("ลำดับไม่ครบ", lambda s: s["order"]["team1"].pop())):
            s2 = copy.deepcopy(st)
            mut(s2)
            try:
                studymod.validate_study(s2, m)
                bad.append(label)
            except studymod.StudyError:
                pass
        check(not bad, "V นิยามการศึกษาผิด (งานซ้ำ/ไม่มีงาน/อยู่ 2 เคส/เลขขาด/คู่พิเศษของตัวเอง/แพ็กเกจผิด/ลำดับ) → ไม่รับ", bad)

        t1 = client_login(S, "team1", users["team1"][1])
        t2 = client_login(S, "team2", users["team2"][1])
        doc = S.add_user([PKG], name="doc1")
        d = client_login(S, "doc1", doc[1])
        me = t1.get("/api/me").get_json()
        p1 = t1.get("/api/package").get_json()
        check(me["study_mode"] == "mark" and p1["mode"] == "mark" and [it["task_id"] for it in p1["items"]] == ["T001", "T002", "T003", "T006"]
              and [c["no"] for c in p1["cases"]] == [1, 5, 2] and all(it["is_repeat_of"] is None for it in p1["items"]),
              "V ผู้มาร์ก team1 เห็นเคสของตัวเอง + คู่พิเศษ (เคส 5) ปนในรายการตามลำดับ · ไม่มีงานซ้ำเดิม", p1.get("cases"))
        pd = d.get("/api/package").get_json()
        check(pd["mode"] == "review" and [c["no"] for c in pd["cases"]] == [1, 2, 3, 4]
              and [it["task_id"] for it in pd["items"]] == ["T001", "T002", "T006", "T003", "T004"],
              "V หมอเห็นเฉพาะเคส 1–4 (ไม่เห็นเคสพิเศษของทีม) เรียงตามเลขเคส", pd.get("cases"))
        tx = S.add_user([], role="team", name="team9")
        t9 = client_login(S, "team9", tx[1])
        r9 = t9.get("/api/package")
        check(r9.status_code == 403 and "admin" in r9.get_json()["error"], "V บัญชีทีมที่ไม่ใช่ผู้มาร์ก → ใช้หน้า admin.html", r9.status_code)
        T = targets()
        pairs6 = list(zip(T["T006_X.png"][:4], T["T006_F.jpg"][:4]))
        pairs1 = list(zip(T["T001_X.png"][:4], T["T001_F.jpg"][:4]))
        check(put(t2, "T001", task_with(pairs1)).status_code == 404 and put(t1, "T004", task_with(pairs1)).status_code == 404
              and put(t1, "T001", task_with(pairs1)).status_code == 200 and put(t2, "T006", task_with(pairs6)).status_code == 200,
              "V บันทึกได้เฉพาะงานในรายการของตัวเอง (คู่พิเศษ T006 ของ team2 ได้ · งานของอีกคนไม่ได้)")
        check(t1.get("/api/image/T001/xray").status_code == 200 and t1.get("/api/image/T004/xray").status_code == 404
              and d.get("/api/image/T004/fluoro").status_code == 200 and d.get("/api/image/T005/xray").status_code == 404,
              "V ภาพ: เปิดได้เฉพาะงานในรายการของตัวเอง (งานซ้ำเดิม T005 ไม่อยู่ในการศึกษา)")
        check(t1.put("/api/meta", json={"current_index": 3}, headers=H).status_code == 200
              and t1.put("/api/meta", json={"current_index": 4}, headers=H).status_code == 400,
              "V ตำแหน่งงานล่าสุดเทียบกับรายการของผู้ใช้ (team1 มี 4 งาน)")

        # R: จุดของทีมที่หมอเห็น
        assert put(t1, "T006", task_with(pairs6)).status_code == 200
        assert put(t1, "T002", task_with([], "unmarkable", "no_overlap")).status_code == 200
        st_d = d.get("/api/state").get_json()
        sd1 = st_d["seeds"]["T001"]
        check(sd1 and sd1["xray"][0]["x"] == pairs1[0][0][0] and st_d["seeds"]["T002"]["status"] == "unmarkable"
              and st_d["seeds"]["T006"]["fluoro"][3]["y"] == pairs6[3][1][1] and st_d["seeds"]["T004"] is None,
              "R หมอได้จุดของผู้มาร์กหลัก (ไม่ใช่ของคู่พิเศษ) · งานที่ทีมยังไม่ทำ = ไม่มีจุด", {k: bool(v) for k, v in st_d["seeds"].items()})
        assert put(d, "T001", task_with(pairs1)).status_code == 200                     # ยืนยันไม่แก้
        moved = [list(p) for p in pairs6]
        moved[0] = [[pairs6[0][0][0] + 3, pairs6[0][0][1] + 4], pairs6[0][1]]
        assert put(d, "T006", task_with(moved)).status_code == 200                       # แก้จุด 1 บนเอกซเรย์ 5 px
        assert put(d, "T002", task_with([], "unmarkable", "no_overlap")).status_code == 200
        assert put(t1, "T001", task_with([[[10, 10], [10, 10]]] + pairs1[1:]), base=1).status_code == 200   # ทีมแก้หลังหมอเห็น
        st_d = d.get("/api/state").get_json()
        check(st_d["seeds"]["T001"]["xray"][0]["x"] == pairs1[0][0][0], "R หมอบันทึกแล้ว: จุดของทีมที่หมอเห็นถูกเก็บไว้ ไม่เปลี่ยนตามที่ทีมแก้ภายหลัง")
        con = S.con()
        doc_x = con.execute("SELECT data FROM tasks_latest t JOIN users u ON u.id = t.user_id WHERE u.username = 'team1' AND task_id = 'T006'").fetchone()[0]
        con.close()
        check(json.loads(doc_x)["xray"][0]["x"] == pairs6[0][0][0], "R หมอแก้จุด → จุดของทีมบนเซิร์ฟเวอร์ไม่ถูกเขียนทับ")
        con = S.con()
        ex = studymod.export_study(con, st, m)
        con.close()
        byt = {t["task_id"]: t for t in ex["tasks"]}
        rv = {t: byt[t]["reviews"][0] for t in byt}
        it6 = next(it for it in m["items"] if it["task_id"] == "T006")
        b = it6["box_xyxy"]
        mv = next(x for x in rv["T006"]["moves"] if x["side"] == "xray" and x["point"] == 1)
        check(rv["T001"]["review_status"] == "confirmed" and rv["T006"]["review_status"] == "edited" and rv["T006"]["points_changed"] == 1
              and rv["T002"]["review_status"] == "unmarkable" and rv["T004"]["review_status"] == "not_started"
              and abs(mv["px"] - 5.0) < 1e-6 and abs(mv["pct"] - 500 / math.hypot(b[2] - b[0], b[3] - b[1])) < 1e-3,
              "R สถานะการตรวจ: ยืนยันไม่แก้ / แก้ (ระยะ 5 px และ % ของเส้นทแยงกรอบ) / มาร์กไม่ได้ / ยังไม่เริ่ม",
              {t: rv[t]["review_status"] for t in rv})
        sec = next(mm for mm in byt["T006"]["markers"] if mm["role"] == "second")
        check(sec["username"] == "team2" and sec["extra_case_no"] == 6 and sec["task"]["status"] == "done"
              and len(byt["T006"]["markers"][0]["history"]) >= 1 and len(rv["T001"]["history"]) == 1,
              "R ส่งออก: จุดของผู้มาร์กหลัก + ผู้มาร์กคนที่สอง (คู่พิเศษ) + ของหมอ พร้อมประวัติทุกครั้ง")
        head, rws = studymod.export_rows(ex)
        r6 = dict(zip(head, next(r for r in rws if r[1] == "T006")))
        check(len(rws) == 5 and r6["review_status"] == "edited" and float(r6["move_x1_px"]) == 5.0 and r6["marker2"] == "team2"
              and r6["marker"] == "team1" and r6["case_no"] == 2, "R CSV: 1 แถวต่องานต่อหมอ · จุด/สถานะ/ระยะแก้ · ผู้มาร์กคนที่สอง", r6.get("review_status"))
        tc = S.app.test_client()
        tc.post("/api/login", json={"username": "team1", "password": users["team1"][1]}, headers=H)
        ov = tc.get("/api/admin/overview").get_json()["study"]
        csv_r = tc.get("/api/admin/study-export?format=csv")
        check(ov["summary"]["doc1"]["confirmed"] == 1 and ov["summary"]["doc1"]["edited"] == 1 and ov["summary"]["doc1"]["unmarkable"] == 1
              and ov["summary"]["doc1"]["not_started"] == 2 and ov["cases"][0]["team_done"] == 2
              and csv_r.status_code == 200 and b"review_status" in csv_r.data and "attachment" in csv_r.headers["Content-Disposition"],
              "R หน้าทีม: สรุปการตรวจของหมอ + ความคืบหน้ารายเคส · ดาวน์โหลด CSV", ov["summary"])
        check(d.get("/api/admin/study-export").status_code == 403, "R หมอดาวน์โหลดไฟล์วิเคราะห์ไม่ได้ (403)")
        chk = S.add_user([PKG], name="check1")
        cc = client_login(S, "check1", chk[1])
        cc.get("/api/state")
        assert put(cc, "T001", task_with(pairs1)).status_code == 200
        with_chk = tc.get("/api/admin/overview").get_json()["study"]["doctors"]
        con = S.con()
        con.execute("UPDATE users SET active = 0 WHERE username = 'check1'")
        con.close()
        after = tc.get("/api/admin/overview").get_json()["study"]["doctors"]
        con = S.con()
        ex2 = studymod.export_study(con, st, m)
        con.close()
        check("check1" in with_chk and "check1" not in after and "check1" not in ex2["doctors"],
              "R บัญชีตรวจระบบที่ปิดแล้ว (disable-user) ไม่ถูกนับในสรุปและไฟล์วิเคราะห์", (with_chk, after))

        # X: ย้ายจุดของทีม
        out = S.tmp / "team_marks.json"
        code, txt = call(manage.cmd_export_marks, S.tmp / "config.toml", out=str(out))
        docm = json.loads(out.read_text(encoding="utf-8"))
        check(code == 0 and {u["username"] for u in docm["users"]} == {"team1", "team2"} and len(docm["tasks_latest"]) == 4
              and "doc1" not in out.read_text(encoding="utf-8"), "X export-marks: จุดของผู้มาร์กทุกคน + ประวัติ + นิยามการศึกษา (ไม่มีของหมอ)", txt)
        S2 = TestServer(packages=(PKG,))
        try:
            code, txt = call(manage.cmd_import_marks, S2.tmp / "config.toml", file=str(out), replace=False)
            con = S2.con()
            n_l = con.execute("SELECT COUNT(*) FROM tasks_latest").fetchone()[0]
            n_e = con.execute("SELECT COUNT(*) FROM task_events").fetchone()[0]
            st2 = studymod.load_study(con)
            con.close()
            check(code == 0 and n_l == 4 and n_e == len(docm["task_events"]) and st2 == st and txt.count("รหัสผ่าน") == 2,
                  "X import-marks บนเครื่องใหม่: จุดและประวัติครบ · ตั้งการศึกษา · สร้างบัญชีทีมที่ยังไม่มี (แสดงรหัสครั้งเดียว)", txt[-200:])
            code2, txt2 = call(manage.cmd_import_marks, S2.tmp / "config.toml", file=str(out), replace=False)
            code3, txt3 = call(manage.cmd_import_marks, S2.tmp / "config.toml", file=str(out), replace=True)
            check(code2 != 0 and "--replace" in txt2 and code3 == 0, "X นำเข้าซ้ำ → ไม่ทับถ้าไม่ใส่ --replace", txt2[-120:])
            dd = S2.add_user([PKG], name="doc7")
            c7 = client_login(S2, "doc7", dd[1])
            s7 = c7.get("/api/state").get_json()
            check(s7["seeds"]["T006"] and s7["seeds"]["T006"]["xray"][0]["x"] == pairs6[0][0][0],
                  "X หลังนำเข้า: หมอบนเครื่องใหม่เห็นจุดของทีมทันที")
        finally:
            S2.stop()
        S3 = TestServer(packages=(PKG,))
        try:
            S3.add_user([PKG], name="team1")                    # ชื่อชนกับบัญชีหมอ
            code, txt = call(manage.cmd_import_marks, S3.tmp / "config.toml", file=str(out), replace=False)
            con = S3.con()
            n = con.execute("SELECT COUNT(*) FROM tasks_latest").fetchone()[0]
            con.close()
            check(code != 0 and "ไม่ใช่บัญชีทีม" in txt and n == 0, "X ชื่อผู้มาร์กชนกับบัญชีหมอบนเครื่องปลายทาง → หยุด ไม่นำเข้าอะไรเลย", txt[-120:])
        finally:
            S3.stop()
    finally:
        S.stop()


def call(fn, conf, **kw):
    out = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out):
        try:
            fn(argparse.Namespace(config=str(conf), **kw))
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
            out.write(str(e.code))
    return code, out.getvalue()


# ---------------------------------------------------------------- L / A / D / T (เบราว์เซอร์)
def wait_task(p, label):
    p.wait_for_function("(l) => document.getElementById('taskLabel').textContent === l && window.__marker.state.imagesReady",
                        arg=label, timeout=20000)


def case_items(p):
    return p.evaluate("() => [...document.querySelectorAll('#caseList .case-item')].map(b => [b.querySelector('b').textContent, "
                      "b.querySelector('span').textContent, b.className])")


def choose_reason(p, code):
    p.wait_for_selector("#dialog:not([hidden])")
    p.check(f"input[name=reason][value={code}]")
    p.click("#btnReasonOk")


def browser_part(browser):
    S = TestServer(packages=(PKG,))
    T = targets()
    try:
        st, users = setup(S)
        errors = []
        c1 = browser.new_context(viewport={"width": 1366, "height": 800})
        c1.add_init_script(ERR_INIT)
        p = c1.new_page()
        p.on("pageerror", lambda e: errors.append(str(e)))
        S.login(c1, "team1", users["team1"][1])
        p.goto(S.base + "/")
        p.wait_for_selector("#caseScreen:not([hidden])", timeout=20000)
        ci = case_items(p)
        check([c[0] for c in ci] == ["เคส 1", "เคส 5", "เคส 2"] and all(c[1] == "ยังไม่เริ่ม" for c in ci)
              and "มาร์กจุด" in p.text_content("#caseTitle"), "L team1: หน้ารายการเคส · เคส 1, 5 (คู่พิเศษ ปน), 2 · ยังไม่เริ่ม", ci)
        p.click("#btnContinue")
        wait_task(p, "เคส 1 · คู่ 1/2")
        check(p.is_disabled("#btnPrev") and p.is_visible("#btnCases") and p.text_content("#btnNext").startswith("ถัดไป"),
              "L ทำต่อ → งานแรกของเคส 1 · ก่อนหน้าปิดที่คู่แรกของเคส · มีปุ่มรายการเคส")
        inp = Input(p, c1, "mouse")
        p.evaluate("() => window.__marker.viewers.xray.resetView()")
        for (x, f) in zip(T["T001_X.png"][:4], T["T001_F.jpg"][:4]):
            place(p, inp, "xray", *x)
            place(p, inp, "fluoro", *f)
        p.click("#btnNext")
        wait_task(p, "เคส 1 · คู่ 2/2")
        p.fill("#jumpInput", "1")
        p.press("#jumpInput", "Enter")
        wait_task(p, "เคส 1 · คู่ 1/2")
        p.fill("#jumpInput", "3")
        p.press("#jumpInput", "Enter")
        p.wait_for_function("() => (document.getElementById('toast').textContent || '').includes('เคสนี้มี 2 คู่')", timeout=5000)
        p.fill("#jumpInput", "2")
        p.press("#jumpInput", "Enter")
        wait_task(p, "เคส 1 · คู่ 2/2")
        check(True, "L ไปที่งาน: เลขคู่ภายในเคส (เกินจำนวนคู่ → แจ้ง)")
        p.click("#btnUnmarkable")
        choose_reason(p, "no_overlap")
        p.wait_for_selector("#caseScreen:not([hidden])", timeout=10000)
        msg = p.text_content("#caseMsg")
        ci = case_items(p)
        check("เคส 1 เสร็จแล้ว" in msg and ci[0][1] == "เสร็จ" and "st-done" in ci[0][2],
              "L ทำครบทุกคู่ในเคส → กลับหน้ารายการเอง · เคส 1 = เสร็จ", (msg, ci[0]))
        p.check("#caseFilter")
        hidden = [c[0] for c in case_items(p)]
        p.uncheck("#caseFilter")
        check("เคส 1" not in hidden and len(hidden) == 2, "L ตัวกรอง: แสดงเฉพาะเคสที่ยังไม่เสร็จ", hidden)
        p.click("#btnContinue")
        wait_task(p, "เคส 5 · คู่ 1/1")
        p.click("#btnSkip")
        p.wait_for_selector("#caseScreen:not([hidden])", timeout=10000)
        ci = case_items(p)
        check(ci[1][0] == "เคส 5" and ci[1][1].startswith("มีงานข้าม") and "st-skip" in ci[1][2],
              "L ทำต่อ → เคสถัดไปที่ยังไม่เสร็จ · ข้ามภายในเคส → กลับรายการ เคสขึ้น มีงานข้าม", ci[1])

        # A: ตัวช่วยของทีม (T006 ฟลู = บริเวณในกรอบที่ขยาย/หมุน → affine ตรง)
        p.click("[data-case='2']")
        wait_task(p, "เคส 2 · คู่ 1/1")
        tx, tf = T["T006_X.png"], T["T006_F.jpg"]
        p.evaluate("() => window.__marker.viewers.xray.resetView()")
        for i in range(3):
            place(p, inp, "xray", *tx[i])
            place(p, inp, "fluoro", *tf[i])
        g0 = p.evaluate("() => window.__marker.ghostFor('fluoro')")
        place(p, inp, "xray", *tx[3])
        g = p.evaluate("() => window.__marker.ghostFor('fluoro')")
        check(g0 is None and g and g["k"] == 3 and math.hypot(g["x"] - tf[3][0], g["y"] - tf[3][1]) < 4,
              "A วางครบ 3 คู่ + จุด 4 บนเอกซเรย์ → แสดงตำแหน่งที่คาดบนฟลู (ตรงเป้าภายใน 4 px)", g)
        place(p, inp, "fluoro", *tf[4])
        w_bad = p.text_content("#warnText")
        p.evaluate("() => window.__marker.undo()")
        place(p, inp, "fluoro", *tf[3])
        w_ok = p.text_content("#warnText")
        check("จุด 4 อาจไม่ตรงคู่" in w_bad and "อาจไม่ตรงคู่" not in w_ok,
              "A จุดที่ 4 ผิดที่ → เตือน จุด 4 อาจไม่ตรงคู่ (ชี้คู่ที่วางล่าสุด) · วางถูก → ไม่เตือน", (w_bad, w_ok))
        p.click("#btnNext")
        p.wait_for_selector("#caseScreen:not([hidden])", timeout=10000)
        p.evaluate("() => window.__marker.flushSave()")
        rev6, team6 = S.task_row("team1", PKG, "T006")
        check(team6 and team6["status"] == "done" and all(team6["xray"]), "A จุดของทีมบันทึกขึ้นเซิร์ฟเวอร์", rev6)

        # D: หมอตรวจ
        doc = S.add_user([PKG], name="doc1")
        c2 = browser.new_context(viewport={"width": 1366, "height": 800})
        c2.add_init_script(ERR_INIT)
        q = c2.new_page()
        q.on("pageerror", lambda e: errors.append(str(e)))
        q.goto(S.link(doc[1]))
        q.wait_for_selector("#caseScreen:not([hidden])", timeout=20000)
        ci = case_items(q)
        check([c[0] for c in ci] == ["เคส 1", "เคส 2", "เคส 3", "เคส 4"] and "ตรวจ" in q.text_content("#caseTitle"),
              "D หมอ: รายการเคส 1–4 (ไม่มีเคสพิเศษ 5, 6)", ci)
        q.click("#btnContinue")
        wait_task(q, "เคส 1 · คู่ 1/2")
        m1 = marks(q)
        _, team1 = S.task_row("team1", PKG, "T001")
        same = all(abs(a["x"] - b["x"]) < 1e-6 and abs(a["y"] - b["y"]) < 1e-6 for a, b in zip(m1["xray"], team1["xray"]))
        check(same and q.text_content("#btnNext").startswith("ยืนยัน") and "ตรวจจุดของทีม" in q.text_content("#hintText")
              and q.evaluate("() => window.__marker.ghostFor('fluoro')") is None,
              "D เปิดงาน: เห็นจุด 4 คู่ของทีม · ปุ่ม ยืนยัน · ไม่มีตัวช่วยคาดตำแหน่ง", q.text_content("#hintText"))
        q.click("#btnNext")
        q.wait_for_function("() => (document.getElementById('toast').textContent || '').includes('ไม่ได้แก้')", timeout=5000)
        wait_task(q, "เคส 1 · คู่ 2/2")
        hint2 = q.text_content("#hintText")
        q.click("#btnUnmarkable")
        choose_reason(q, "no_overlap")
        q.wait_for_selector("#caseScreen:not([hidden])", timeout=10000)
        check("ทีมระบุว่ามาร์กไม่ได้" in hint2, "D งานที่ทีมมาร์กไม่ได้ → บอกหมอ · หมอกด มาร์กไม่ได้ ได้", hint2)
        q.click("[data-case='2']")
        wait_task(q, "เคส 2 · คู่ 1/1")
        iq = Input(q, c2, "mouse")
        old = marks(q)["xray"][0]
        x, y = to_page(q, "xray", old["x"], old["y"])
        iq.down(x, y, hold=False)
        ses = session(q, "xray")
        iq.move(x, y, x + 30, y)
        iq.up(x + 30, y)
        new = marks(q)["xray"][0]
        q.click("#btnNext")
        q.wait_for_function("() => (document.getElementById('toast').textContent || '').includes('แก้ 1 จุด')", timeout=5000)
        q.wait_for_selector("#caseScreen:not([hidden])", timeout=10000)
        q.evaluate("() => window.__marker.flushSave()")
        _, team6b = S.task_row("team1", PKG, "T006")
        _, doc6 = S.task_row("doc1", PKG, "T006")
        check(ses and ses["mode"] == "move" and new["x"] > old["x"] and team6b["xray"][0]["x"] == team6["xray"][0]["x"]
              and doc6["xray"][0]["x"] == new["x"] and doc6["status"] == "done",
              "D ลากแก้ผ่านแว่นขยายแล้วยืนยัน → แจ้ง แก้ 1 จุด · จุดของทีมบนเซิร์ฟเวอร์ไม่ถูกเขียนทับ", (old, new))

        # T: หน้าทีม
        pa = c1.new_page()
        pa.goto(S.base + "/admin.html")
        pa.wait_for_selector("#studyCard:not([hidden])", timeout=10000)
        summ = pa.text_content("#studySummary")
        check(pa.is_visible("#btnMark") and "ยืนยันไม่แก้ 1" in summ and "แก้ 1" in summ and "มาร์กไม่ได้ 1" in summ
              and pa.locator("#studyRows tr").count() == 4, "T หน้าทีม: ปุ่มมาร์กจุด · สรุป ยืนยัน/แก้/มาร์กไม่ได้ · ความคืบหน้ารายเคส", summ)
        r = c1.request.get(S.base + "/api/admin/study-export?format=csv")
        lines = r.text().lstrip("﻿").splitlines()
        data = list(csv.DictReader(lines[1:]))
        by = {d["task_id"]: d for d in data}
        check(r.ok and by["T001"]["review_status"] == "confirmed" and by["T006"]["review_status"] == "edited"
              and float(by["T006"]["move_x1_px"]) > 0 and by["T002"]["review_status"] == "unmarkable" and lines[0].startswith("# COCO"),
              "T ดาวน์โหลด CSV วิเคราะห์จากหน้าทีม: สถานะการตรวจและระยะที่หมอแก้ถูกต้อง", {k: v["review_status"] for k, v in by.items()})
        check(not errors, "L/D ไม่มี error ในหน้าเว็บ", errors[:3])
        c1.close()
        c2.close()
    finally:
        S.stop()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not (GEN / PKG / "manifest.json").exists():
        sys.exit("ยังไม่มีภาพทดสอบ: รัน python tests/make_test_images.py ก่อน")
    server_part()
    with sync_playwright() as pw:
        br = pw.chromium.launch(channel="msedge")
        try:
            browser_part(br)
        except Exception as e:
            check(False, "! browser_part ล้มกลางคัน", repr(e)[:400])
        br.close()
    for ok, label, detail in rows:
        print(f"{'ผ่าน   ' if ok else 'ไม่ผ่าน'}  {label}" + ("" if ok else f"  {detail}"))
    n = sum(1 for r in rows if r[0])
    print(f"\nผ่าน {n} / {len(rows)} รายการ")
    sys.exit(0 if n == len(rows) else 1)


if __name__ == "__main__":
    main()
