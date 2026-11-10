"""แปลง DOCTOR_GUIDE.md เป็นหน้า HTML สำหรับพิมพ์ (A4 1 หน้า)

วิธีใช้:
    python tools/print_guide.py
    แล้วเปิด DOCTOR_GUIDE_print.html ใน Edge → Ctrl+P → เลือกเครื่องพิมพ์ หรือ "บันทึกเป็น PDF"

รองรับ Markdown เฉพาะที่ใช้ในคู่มือ: # หัวข้อ, ## หัวข้อย่อย, รายการ 1. / -, **ตัวหนา**, `โค้ด`
"""

from __future__ import annotations

import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "DOCTOR_GUIDE.md"
OUT = ROOT / "DOCTOR_GUIDE_print.html"

CSS = """
@page { size: A4; margin: 11mm 12mm; }
* { box-sizing: border-box; }
body { font-family: "Leelawadee UI", "Tahoma", sans-serif; font-size: 12pt; line-height: 1.4; color: #000; background: #fff; margin: 0; }
h1 { font-size: 17pt; margin: 0 0 4px; }
.top p { margin: 2px 0; }
.cols { column-count: 2; column-gap: 7mm; margin-top: 6px; }
section { break-inside: avoid; margin: 0 0 9px; }
h2 { font-size: 13pt; margin: 0 0 3px; padding: 2px 6px; background: #e8eef5; border-left: 4px solid #2b6cb0; }
ol, ul { margin: 0; padding-left: 18px; }
li { margin: 1px 0; }
p { margin: 2px 0; }
code { font-family: Consolas, monospace; font-size: 9.2pt; }
.page + .page { break-before: page; }
@media screen { .page + .page { margin-top: 18mm; border-top: 1px dashed #999; padding-top: 8mm; } }
@media screen { body { max-width: 210mm; margin: 12px auto; padding: 0 12mm; } }
"""


def inline(text: str) -> str:
    t = html.escape(text, quote=False)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    return t


PAGEBREAK = "<!-- pagebreak -->"


def convert_page(md: str) -> tuple[str, str]:
    """คืน (หัวเรื่อง, html ของ 1 หน้า)"""
    top, sections, cur = [], [], None
    lst = None                                    # 'ol' / 'ul' ที่กำลังเปิดอยู่
    title = "คู่มือแพทย์"

    def out(s):
        (cur if cur is not None else top).append(s)

    def close_list():
        nonlocal lst
        if lst:
            out(f"</{lst}>")
            lst = None

    for line in md.splitlines():
        s = line.rstrip()
        if not s or s.startswith("<!--"):
            close_list()
            continue
        if s.startswith("# "):
            title = s[2:].strip()
            out(f"<h1>{inline(title)}</h1>")
        elif s.startswith("## "):
            close_list()
            cur = [f"<h2>{inline(s[3:])}</h2>"]
            sections.append(cur)
        elif re.match(r"^\d+\.\s", s) or s.startswith("- "):
            kind = "ul" if s.startswith("- ") else "ol"
            if lst != kind:
                close_list()
                out(f"<{kind}>")
                lst = kind
            out(f"<li>{inline(re.sub(r'^(\d+\.|-)\s+', '', s))}</li>")
        else:
            close_list()
            out(f"<p>{inline(s)}</p>")
    close_list()
    body = '<div class="top">' + "\n".join(top) + "</div>\n<div class=\"cols\">\n"
    body += "\n".join("<section>" + "\n".join(sec) + "</section>" for sec in sections) + "\n</div>"
    return title, body


def convert(md: str) -> str:
    """แยกหน้าด้วยบรรทัด <!-- pagebreak --> · แต่ละหน้าเริ่มหน้ากระดาษใหม่ พิมพ์แยกหน้าได้"""
    pages = [convert_page(part) for part in md.split(PAGEBREAK) if part.strip()]
    body = "\n".join(f'<div class="page">{b}</div>' for _, b in pages)
    title = "คู่มือแพทย์ PelNav"
    return (f'<!doctype html>\n<html lang="th"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head>\n<body>\n{body}\n</body></html>\n")


def main():
    OUT.write_text(convert(SRC.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"เขียน {OUT.name} แล้ว → เปิดใน Edge แล้วกด Ctrl+P")


if __name__ == "__main__":
    main()
