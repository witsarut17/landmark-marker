"""การศึกษาแบบ "ทีมมาร์กก่อน หมอตรวจ" (v1.3) — นิยามเคส มุมมองของผู้ใช้ สถานะการตรวจ และไฟล์ส่งออกสำหรับวิเคราะห์

study (เก็บในตาราง study ของฐานข้อมูล · ไม่มีรหัสเคสจริง/ข้อมูลผู้ป่วย):
  {"format": "pelnav-study", "version": 1, "package_id": "...", "seed": ...,
   "cases": [{"no": 1, "tasks": ["T005", "T017"], "marker": "team1"}, ...],        เคส 1–70 · ผู้มาร์กหลัก
   "extra": [{"no": 71, "task": "T150", "marker": "team1"}, ...],                    คู่วัดความตรงกันระหว่างผู้มาร์ก
   "order": {"team1": [1, 2, 71, 3, ...]}}                                             ลำดับในรายการของผู้มาร์ก (ไม่บังคับ)
ผู้มาร์ก (บัญชีทีม) เห็นเคสของตัวเอง + คู่พิเศษของตัวเอง · หมอเห็นเฉพาะเคส 1–70 · งานซ้ำ (is_repeat_of) ไม่อยู่ในการศึกษา
"""

from __future__ import annotations

import json
import math

from .db import now_iso
from .validate import FINAL

N = 4
FORMAT = "pelnav-study"


class StudyError(ValueError):
    pass


def validate_study(study: dict, manifest: dict) -> list[str]:
    """ตรวจนิยามการศึกษาเทียบกับ manifest · คืนรายการคำเตือน (ข้อผิดพลาดร้ายแรง = StudyError)"""
    if not isinstance(study, dict) or study.get("format") != FORMAT or study.get("version") != 1:
        raise StudyError("ไม่ใช่ไฟล์การศึกษา (format/version ผิด)")
    if study.get("package_id") != manifest["package_id"]:
        raise StudyError(f"package_id ไม่ตรง ({study.get('package_id')} ≠ {manifest['package_id']})")
    items = {it["task_id"]: it for it in manifest["items"]}
    cases = study.get("cases")
    if not isinstance(cases, list) or not cases:
        raise StudyError("ไม่มี cases")
    seen_task, nos, owner = set(), set(), {}
    for c in cases:
        no, tasks, mk = c.get("no"), c.get("tasks"), c.get("marker")
        if not isinstance(no, int) or isinstance(no, bool) or no < 1 or no in nos:
            raise StudyError(f"เลขเคสผิดหรือซ้ำ: {no}")
        nos.add(no)
        if not isinstance(mk, str) or not mk:
            raise StudyError(f"เคส {no}: ไม่มีผู้มาร์ก")
        if not isinstance(tasks, list) or not 1 <= len(tasks) <= 10:
            raise StudyError(f"เคส {no}: tasks ผิด")
        for t in tasks:
            if t not in items:
                raise StudyError(f"เคส {no}: ไม่มีงาน {t} ในแพ็กเกจ")
            if items[t].get("is_repeat_of"):
                raise StudyError(f"เคส {no}: {t} เป็นงานซ้ำ (ไม่ใช้ในการศึกษานี้)")
            if t in seen_task:
                raise StudyError(f"งาน {t} อยู่หลายเคส")
            seen_task.add(t)
            owner[t] = mk
    if sorted(nos) != list(range(1, len(nos) + 1)):
        raise StudyError("เลขเคสต้องเรียง 1..N ไม่ขาด")
    extra_nos = set()
    for e in study.get("extra") or []:
        no, t, mk = e.get("no"), e.get("task"), e.get("marker")
        if not isinstance(no, int) or isinstance(no, bool) or no in nos or no in extra_nos:
            raise StudyError(f"เลขเคสพิเศษผิดหรือซ้ำ: {no}")
        extra_nos.add(no)
        if t not in owner:
            raise StudyError(f"เคสพิเศษ {no}: งาน {t} ไม่อยู่ในเคสใด")
        if owner[t] == mk:
            raise StudyError(f"เคสพิเศษ {no}: {mk} เป็นผู้มาร์กหลักของงานนี้อยู่แล้ว")
    warn = []
    markers = {c["marker"] for c in cases} | {e["marker"] for e in study.get("extra") or []}
    for mk, order in (study.get("order") or {}).items():
        mine = {c["no"] for c in cases if c["marker"] == mk} | {e["no"] for e in study.get("extra") or [] if e["marker"] == mk}
        if sorted(order) != sorted(mine):
            raise StudyError(f"order ของ {mk} ไม่ตรงกับเคสของผู้มาร์กนี้")
    unused = [t for t, it in items.items() if not it.get("is_repeat_of") and t not in seen_task]
    if unused:
        warn.append(f"งานในแพ็กเกจที่ไม่อยู่ในการศึกษา {len(unused)} งาน")
    warn.append(f"ผู้มาร์ก: {', '.join(sorted(markers))}")
    return warn


def markers(study: dict) -> set[str]:
    return {c["marker"] for c in study["cases"]} | {e["marker"] for e in study.get("extra") or []}


def primary_marker(study: dict) -> dict[str, str]:
    return {t: c["marker"] for c in study["cases"] for t in c["tasks"]}


def case_of(study: dict) -> dict[str, int]:
    return {t: c["no"] for c in study["cases"] for t in c["tasks"]}


def view_for(study: dict, username: str, role: str) -> dict | None:
    """มุมมองของผู้ใช้: {"mode": "mark"|"review", "cases": [{"no", "tasks"}], "tasks": [...]} หรือ None (ไม่อยู่ในการศึกษา)"""
    if role == "team" and username in markers(study):
        cs = {c["no"]: list(c["tasks"]) for c in study["cases"] if c["marker"] == username}
        cs.update({e["no"]: [e["task"]] for e in study.get("extra") or [] if e["marker"] == username})
        order = (study.get("order") or {}).get(username) or sorted(cs)
        cases = [{"no": no, "tasks": cs[no]} for no in order]
        mode = "mark"
    elif role == "doctor":
        cases = [{"no": c["no"], "tasks": list(c["tasks"])} for c in sorted(study["cases"], key=lambda c: c["no"])]
        mode = "review"
    else:
        return None
    return {"mode": mode, "cases": cases, "tasks": [t for c in cases for t in c["tasks"]]}


def load_study(con) -> dict | None:
    r = con.execute("SELECT data FROM study WHERE id = 1").fetchone()
    return json.loads(r["data"]) if r else None


def save_study(con, study: dict) -> None:
    con.execute("""INSERT INTO study (id, package_id, data, set_at) VALUES (1, ?, ?, ?)
                   ON CONFLICT (id) DO UPDATE SET package_id = excluded.package_id, data = excluded.data, set_at = excluded.set_at""",
                (study["package_id"], json.dumps(study, ensure_ascii=False, separators=(",", ":")), now_iso()))


# ---------------------------------------------------------------- สถานะการตรวจของหมอ
def _pt(p):
    return (p["x"], p["y"]) if p else None


def review_compare(seed: dict | None, final: dict | None, box, fluoro_size, fluoro_area=None) -> dict:
    """เทียบจุดที่หมอยืนยัน (final) กับจุดของทีมที่หมอเห็น (seed)
    review_status: not_started / in_progress / skipped / unmarkable / confirmed (ไม่แก้) / edited (แก้ ย้าย/เพิ่ม/ลบจุด)
    ระยะที่แก้ต่อจุด: พิกเซล และ % — เอกซเรย์เทียบเส้นทแยงกรอบ · ฟลูเทียบเส้นผ่านศูนย์กลางวงกลมฟลู (ไม่มี = เส้นทแยงภาพฟลู)"""
    out = {"review_status": "not_started", "points_changed": 0, "moves": []}
    if not final:
        return out
    st = final.get("status")
    if st in (None, "todo"):
        return out
    if st == "unmarkable":
        out["review_status"] = "unmarkable"
    elif st == "skipped":
        out["review_status"] = "skipped"
    elif st not in FINAL:
        out["review_status"] = "in_progress"
    diag_x = math.hypot(box[2] - box[0], box[3] - box[1]) or 1.0
    diam_f = 2 * math.sqrt(fluoro_area / math.pi) if fluoro_area else math.hypot(*fluoro_size)
    changed = 0
    for side, ref in (("xray", diag_x), ("fluoro", diam_f)):
        s_pts = (seed or {}).get(side) or [None] * N
        f_pts = final.get(side) or [None] * N
        for i in range(N):
            a, b = _pt(s_pts[i] if i < len(s_pts) else None), _pt(f_pts[i] if i < len(f_pts) else None)
            if a and b:
                d = math.hypot(b[0] - a[0], b[1] - a[1])
                kind = "moved" if d > 0.05 else "same"
            elif a or b:
                d, kind = None, ("added" if b else "removed")
            else:
                continue
            if kind != "same":
                changed += 1
            out["moves"].append({"side": side, "point": i + 1, "kind": kind,
                                 "px": round(d, 2) if d is not None else None,
                                 "pct": round(100 * d / ref, 3) if d is not None else None})
    out["points_changed"] = changed
    if out["review_status"] == "not_started" and st in FINAL:
        out["review_status"] = "edited" if changed else "confirmed"
    return out


# ---------------------------------------------------------------- ส่งออกสำหรับวิเคราะห์
COORD_NOTE = ("COCO pixel coordinates of the package image (= clean image pixel grid, identity transform); "
              "origin top-left corner of top-left pixel; x right, y down")


def _latest(con, user_id, pkg, tid):
    r = con.execute("SELECT rev, data, saved_at FROM tasks_latest WHERE user_id = ? AND package_id = ? AND task_id = ?",
                    (user_id, pkg, tid)).fetchone()
    return (json.loads(r["data"]), r["rev"], r["saved_at"]) if r else (None, 0, None)


def _history(con, user_id, pkg, tid):
    return [{"rev": r["rev"], "saved_at": r["saved_at"], "task": json.loads(r["data"])}
            for r in con.execute("SELECT rev, data, saved_at FROM task_events WHERE user_id = ? AND package_id = ? AND task_id = ? "
                                 "ORDER BY id", (user_id, pkg, tid))]


def seed_for(con, study: dict, doctor_id: int, tid: str, users: dict) -> dict | None:
    """จุดของทีมที่หมอเห็นในงานนี้: snapshot ตอนหมอบันทึกครั้งแรก (ถ้ามี) ไม่งั้นงานล่าสุดของผู้มาร์กหลัก"""
    r = con.execute("SELECT data FROM review_seeds WHERE user_id = ? AND package_id = ? AND task_id = ?",
                    (doctor_id, study["package_id"], tid)).fetchone()
    if r:
        return json.loads(r["data"]) if r["data"] else None
    mk = users.get(primary_marker(study).get(tid))
    return _latest(con, mk, study["package_id"], tid)[0] if mk else None


def export_study(con, study: dict, manifest: dict, with_history: bool = True) -> dict:
    pkg = study["package_id"]
    items = {it["task_id"]: it for it in manifest["items"]}
    users = {r["username"]: r["id"] for r in con.execute("SELECT id, username FROM users")}
    doctors = [r["username"] for r in con.execute(
        "SELECT u.username FROM users u JOIN assignments a ON a.user_id = u.id WHERE u.role = 'doctor' AND u.active = 1 AND a.package_id = ? "
        "ORDER BY u.username", (pkg,))]
    second = {e["task"]: (e["marker"], e["no"]) for e in study.get("extra") or []}
    tasks = []
    for c in sorted(study["cases"], key=lambda c: c["no"]):
        for tid in c["tasks"]:
            it = items[tid]
            rec = {"case_no": c["no"], "task_id": tid, "box_xyxy": it["box_xyxy"], "xray_size": it["xray_size"],
                   "fluoro_size": it["fluoro_size"], "fluoro_area": it.get("fluoro_area"), "markers": [], "reviews": []}
            for role, mk in (("primary", c["marker"]), ("second", second.get(tid, (None,))[0])):
                if not mk:
                    continue
                uid = users.get(mk)
                data, rev, saved = _latest(con, uid, pkg, tid) if uid else (None, 0, None)
                m = {"role": role, "username": mk, "rev": rev, "saved_at": saved, "task": data}
                if role == "second":
                    m["extra_case_no"] = second[tid][1]
                if with_history and uid:
                    m["history"] = _history(con, uid, pkg, tid)
                rec["markers"].append(m)
            for d in doctors:
                uid = users[d]
                data, rev, saved = _latest(con, uid, pkg, tid)
                seed = seed_for(con, study, uid, tid, users)
                rv = {"username": d, "rev": rev, "saved_at": saved, "seed": seed, "task": data,
                      **review_compare(seed, data, it["box_xyxy"], it["fluoro_size"], it.get("fluoro_area"))}
                if with_history:
                    rv["history"] = _history(con, uid, pkg, tid)
                rec["reviews"].append(rv)
            tasks.append(rec)
    return {"format": "pelnav-study-export", "version": 1, "exported_at": now_iso(), "package_id": pkg,
            "coord_convention": COORD_NOTE, "n_cases": len(study["cases"]), "n_tasks": len(tasks),
            "doctors": doctors, "tasks": tasks}


def _pts(task, side):
    out = []
    for i in range(N):
        p = ((task or {}).get(side) or [None] * N)[i] if task else None
        out += [p["x"] if p else "", p["y"] if p else ""]
    return out


def export_rows(doc: dict) -> tuple[list[str], list[list]]:
    """CSV: 1 แถวต่อ (งาน, หมอ) — จุดของผู้มาร์กหลัก/ผู้มาร์กคนที่สอง/หมอ + สถานะการตรวจ + ระยะที่หมอแก้ต่อจุด"""
    pt_cols = lambda p: [f"{p}_{s}{i}_{a}" for s in ("x", "f") for i in range(1, N + 1) for a in ("x", "y")]  # noqa: E731
    mv_cols = [f"move_{s}{i}_{u}" for s in ("x", "f") for i in range(1, N + 1) for u in ("px", "pct")]
    head = (["case_no", "task_id", "box_x1", "box_y1", "box_x2", "box_y2",
             "marker", "marker_status", "marker_reason", "marker_duration_ms", "marker_finished_at"] + pt_cols("m")
            + ["marker2", "marker2_case_no", "marker2_status"] + pt_cols("m2")
            + ["doctor", "doctor_status", "review_status", "points_changed", "doctor_reason", "doctor_reason_text",
               "doctor_duration_ms", "doctor_finished_at"] + pt_cols("d") + mv_cols)
    rows = []
    for t in doc["tasks"]:
        mk = next((m for m in t["markers"] if m["role"] == "primary"), {})
        m2 = next((m for m in t["markers"] if m["role"] == "second"), None)
        mt, m2t = mk.get("task") or {}, (m2 or {}).get("task") or {}
        base = [t["case_no"], t["task_id"], *t["box_xyxy"], mk.get("username", ""), mt.get("status", ""), mt.get("reason") or "",
                mt.get("duration_ms", ""), mt.get("finished_at") or ""] + _pts(mt, "xray") + _pts(mt, "fluoro")
        base += [(m2 or {}).get("username", ""), (m2 or {}).get("extra_case_no", ""), m2t.get("status", "")] + _pts(m2t, "xray") + _pts(m2t, "fluoro")
        for rv in t["reviews"] or [None]:
            if rv is None:
                rows.append(base + [""] * (8 + 16 + len(mv_cols)))
                continue
            dt = rv.get("task") or {}
            mv = {(m["side"][0], m["point"]): m for m in rv["moves"]}
            mvv = []
            for s in ("x", "f"):
                for i in range(1, N + 1):
                    m = mv.get((s, i))
                    mvv += [m["px"] if m and m["px"] is not None else "", m["pct"] if m and m["pct"] is not None else ""]
            rows.append(base + [rv["username"], dt.get("status", ""), rv["review_status"], rv["points_changed"], dt.get("reason") or "",
                                dt.get("reason_text") or "", dt.get("duration_ms", ""), dt.get("finished_at") or ""]
                        + _pts(dt, "xray") + _pts(dt, "fluoro") + mvv)
    return head, rows


def progress(con, study: dict, manifest: dict) -> dict:
    """ความคืบหน้ารายเคส (ทีมมาร์ก + หมอตรวจ) และสรุปการตรวจของหมอแต่ละคน"""
    pkg = study["package_id"]
    users = {r["username"]: r["id"] for r in con.execute("SELECT id, username FROM users")}
    items = {it["task_id"]: it for it in manifest["items"]}

    def statuses(uid):
        return {r["task_id"]: json.loads(r["data"]) for r in con.execute(
            "SELECT task_id, data FROM tasks_latest WHERE user_id = ? AND package_id = ?", (uid, pkg))} if uid else {}
    doctors = [r["username"] for r in con.execute(
        "SELECT u.username FROM users u JOIN assignments a ON a.user_id = u.id WHERE u.role = 'doctor' AND u.active = 1 AND a.package_id = ? "
        "ORDER BY u.username", (pkg,))]
    mk_tasks = {mk: statuses(users.get(mk)) for mk in markers(study)}
    dr_tasks = {d: statuses(users[d]) for d in doctors}
    summary = {d: {"confirmed": 0, "edited": 0, "unmarkable": 0, "in_progress": 0, "skipped": 0, "not_started": 0} for d in doctors}
    cases = []
    for c in sorted(study["cases"], key=lambda c: c["no"]):
        team = mk_tasks.get(c["marker"], {})
        row = {"no": c["no"], "n": len(c["tasks"]), "marker": c["marker"],
               "team_done": sum(1 for t in c["tasks"] if (team.get(t) or {}).get("status") in FINAL),
               "team_skipped": sum(1 for t in c["tasks"] if (team.get(t) or {}).get("status") == "skipped"), "reviews": {}}
        for d in doctors:
            cnt = {}
            for t in c["tasks"]:
                it = items[t]
                seed = seed_for(con, study, users[d], t, users)
                rs = review_compare(seed, dr_tasks[d].get(t), it["box_xyxy"], it["fluoro_size"], it.get("fluoro_area"))["review_status"]
                summary[d][rs] = summary[d].get(rs, 0) + 1
                cnt[rs] = cnt.get(rs, 0) + 1
            row["reviews"][d] = cnt
        cases.append(row)
    extra = []
    for e in study.get("extra") or []:
        st = (mk_tasks.get(e["marker"], {}).get(e["task"]) or {}).get("status")
        extra.append({"no": e["no"], "marker": e["marker"], "done": st in FINAL})
    team = {mk: {"cases": sum(1 for c in study["cases"] if c["marker"] == mk),
                 "tasks": sum(len(c["tasks"]) for c in study["cases"] if c["marker"] == mk)
                 + sum(1 for e in study.get("extra") or [] if e["marker"] == mk),
                 "done": sum(1 for t in mk_tasks.get(mk, {}).values() if t.get("status") in FINAL)} for mk in sorted(markers(study))}
    return {"package_id": pkg, "cases": cases, "extra": extra, "team": team, "doctors": doctors, "summary": summary}
