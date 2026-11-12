"""เปลี่ยนเวอร์ชันของเว็บในที่เดียว: marker/version.js + ?v= ของทุกไฟล์ใน marker/index.html

ทุกครั้งที่จะ push เว็บเวอร์ชันใหม่ ต้องรันสคริปต์นี้ก่อน
  - ?v= ทำให้ iPad/เบราว์เซอร์ไม่ใช้ไฟล์เก่าในแคชปนกับไฟล์ใหม่
  - เว็บที่เปิดค้างอยู่ (เช่น ไอคอนบนหน้าจอโฮม) จะเห็นว่า version.js ใหม่กว่า แล้วบันทึกงานและโหลดใหม่เอง

วิธีใช้:  .venv\\Scripts\\python tools/bump_version.py 0.8.1
          .venv\\Scripts\\python tools/bump_version.py --check      (ตรวจว่าเลขตรงกันทุกที่)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MARKER = Path(__file__).resolve().parents[1] / "marker"
VERSION_JS = MARKER / "version.js"
INDEX = MARKER / "index.html"
VER_RE = re.compile(r"window\.PELNAV_VERSION = '([0-9]+\.[0-9]+\.[0-9]+)';")
ASSET_RE = re.compile(r'((?:src|href)="[\w.-]+\.(?:js|css))(?:\?v=[^"]*)?"')


def current() -> str:
    m = VER_RE.search(VERSION_JS.read_text(encoding="utf-8"))
    if not m:
        sys.exit("หยุด: อ่านเวอร์ชันใน marker/version.js ไม่ได้")
    return m.group(1)


def index_versions() -> set[str]:
    html = INDEX.read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="[\w.-]+\.(?:js|css)(\?v=[^"]*)?"', html)
    return {r[3:] if r else "" for r in refs}


def check() -> bool:
    v = current()
    found = index_versions()
    ok = found == {v}
    print(f"version.js = {v} · index.html ?v= {sorted(found)} → {'ตรงกัน' if ok else 'ไม่ตรง'}")
    return ok


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")     # คอนโซล Windows ไม่ใช่ UTF-8
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("version", nargs="?", help="เวอร์ชันใหม่ เช่น 0.8.1")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check or not a.version:
        sys.exit(0 if check() else 1)
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", a.version):
        sys.exit("หยุด: เวอร์ชันต้องเป็นแบบ 0.8.1")
    old = current()
    js = VERSION_JS.read_text(encoding="utf-8")
    VERSION_JS.write_text(VER_RE.sub(f"window.PELNAV_VERSION = '{a.version}';", js), encoding="utf-8")
    html = INDEX.read_text(encoding="utf-8")
    INDEX.write_text(ASSET_RE.sub(lambda m: f'{m.group(1)}?v={a.version}"', html), encoding="utf-8")
    print(f"{old} → {a.version}")
    sys.exit(0 if check() else 1)


if __name__ == "__main__":
    main()
