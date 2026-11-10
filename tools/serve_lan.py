"""เปิดเว็บมาร์กจุดให้ iPad ที่อยู่ใน Wi-Fi/ฮอตสปอตเดียวกันเข้าได้ (ใช้ระหว่างทดสอบเท่านั้น)

วิธีใช้ (จากโฟลเดอร์โปรเจกต์):
    python tools/serve_lan.py --with-testdata

- เปิดให้เห็น "เฉพาะโฟลเดอร์ marker/" (ตัวเว็บ) ไม่เปิดโฟลเดอร์อื่นของโปรเจกต์
- --with-testdata : เพิ่มลิงก์ /testdata.zip ให้ iPad ดาวน์โหลดภาพทดสอบสังเคราะห์ (ไม่มีภาพผู้ป่วย)
- ส่ง header no-store -> iPad ได้โค้ดล่าสุดทุกครั้ง ไม่ต้องล้างแคช
- ปิดด้วย Ctrl+C
"""

from __future__ import annotations

import argparse
import functools
import io
import socket
import sys
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "marker"
GEN = ROOT / "tests" / "generated"
TEST_PACKAGES = ["test_package", "test_package_big", "bad_size_package", "bad_exif_package"]


def build_testdata_zip() -> bytes:
    missing = [p for p in TEST_PACKAGES if not (GEN / p / "manifest.json").exists()]
    if missing:
        sys.exit(f"ยังไม่มีภาพทดสอบ {missing}: รัน python tests/make_test_images.py ก่อน")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:     # ภาพบีบอัดแล้ว ไม่ต้องบีบซ้ำ
        for pkg in TEST_PACKAGES:
            for f in sorted((GEN / pkg).iterdir()):
                if f.is_file():
                    z.write(f, f"pelnav_testdata/{pkg}/{f.name}")
    return buf.getvalue()


def local_ipv4() -> list[str]:
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    return sorted(ips)


class Handler(SimpleHTTPRequestHandler):
    testdata: bytes | None = None

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path.split("?")[0] == "/testdata.zip":
            if self.testdata is None:
                self.send_error(404, "start with --with-testdata")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", 'attachment; filename="pelnav_testdata.zip"')
            self.send_header("Content-Length", str(len(self.testdata)))
            self.end_headers()
            self.wfile.write(self.testdata)
            return
        super().do_GET()

    def log_message(self, fmt, *args):
        sys.stdout.write(f"  [{self.client_address[0]}] {fmt % args}\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--with-testdata", action="store_true", help="เพิ่มลิงก์ /testdata.zip (ภาพทดสอบสังเคราะห์)")
    ap.add_argument("--local", action="store_true", help="เปิดเฉพาะในเครื่องนี้ (127.0.0.1) — ใช้ตอนเปิดภาพจริงบนโน้ตบุ๊ก")
    args = ap.parse_args()

    if args.with_testdata:
        Handler.testdata = build_testdata_zip()
    handler = functools.partial(Handler, directory=str(WEB))
    try:
        srv = ThreadingHTTPServer(("127.0.0.1" if args.local else "0.0.0.0", args.port), handler)
    except OSError as e:
        sys.exit(f"เปิดพอร์ต {args.port} ไม่ได้ ({e}) — อาจมีเซิร์ฟเวอร์อื่นเปิดอยู่ ลอง --port 8001")

    ips = [] if args.local else local_ipv4()
    print("=" * 60)
    print("เปิดเว็บแล้ว (ปิดด้วย Ctrl+C)")
    print(f"  บนโน้ตบุ๊กนี้ : http://localhost:{args.port}/")
    if ips:
        print("  บน iPad (พิมพ์ใน Safari อันใดอันหนึ่ง):")
        for ip in ips:
            print(f"      http://{ip}:{args.port}/")
        if any(ip.startswith("192.168.137.") for ip in ips):
            print("      (192.168.137.1 = ฮอตสปอตของ Windows เอง)")
    elif args.local:
        print("  (--local: เครื่องอื่นเข้าไม่ได้)")
    else:
        print("  หา IP ไม่เจอ — พิมพ์ ipconfig แล้วดู IPv4 Address")
    if Handler.testdata:
        mb = len(Handler.testdata) / 1e6
        print(f"  ภาพทดสอบ ({mb:.1f} MB): เติม testdata.zip ท้ายลิงก์ เช่น http://{ips[0] if ips else 'IP'}:{args.port}/testdata.zip")
    print("=" * 60)
    print("บรรทัดด้านล่างจะขึ้นเมื่อมีเครื่องเข้ามา (ใช้ดูว่า iPad ต่อถึงไหม):")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nปิดเซิร์ฟเวอร์แล้ว")


if __name__ == "__main__":
    main()
