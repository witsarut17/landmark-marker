// ค่าตั้งทั้งหมดของเว็บ แก้ที่ไฟล์นี้ไฟล์เดียว (ไม่ต้องแตะโค้ดส่วนอื่น)
window.MARKER_CONFIG = Object.freeze({
  APP_VERSION: '0.6.1',

  view: Object.freeze({
    fitMargin: 0.96,             // ตอนรีเซ็ต ภาพกินพื้นที่ 96% ของช่อง
    boxMargin: 0.15,             // เปิดงาน: เอกซเรย์ซูมพอดีกรอบ box_xyxy เผื่อขอบด้านละ 15% ของขนาดกรอบ
    minZoomRelative: 0.5,        // ซูมออกได้ถึงครึ่งหนึ่งของขนาดพอดีจอ
    maxScreenPxPerImagePx: 10,   // ซูมเข้าสูงสุด: 1 px ภาพ = 10 px จอ (1 px จอ ≥ 0.1 px ภาพ)
    wheelZoomSpeed: 0.0015,      // ล้อเมาส์
    pinchWheelZoomSpeed: 0.01,   // ทัชแพด pinch (ส่งมาเป็น wheel + ctrlKey)
    pixelatedAboveScale: 2,      // ซูมเกิน 2 px จอ/พิกเซลภาพ -> แสดงพิกเซลคม ไม่เบลอ
  }),

  input: Object.freeze({
    tapSlopPx: 8,                // ขยับไม่เกินนี้ = แตะ/กดค้าง (ไม่ใช่ลาก)
    tapMaxMs: 500,               // นิ้ว: แตะนานไม่เกินนี้ = แตะ
    mouseHoldMs: 250,            // เมาส์: กดค้างเท่านี้บนที่ว่าง -> เริ่มวางจุด
    touchHoldPlaceMs: 350,       // นิ้ว (โหมดนิ้ววางจุด): กดค้างเท่านี้ -> เริ่มวางจุด
    touchHoldPointMs: 250,       // นิ้ว: กดค้างบนจุดเดิมเท่านี้ -> เริ่มลากจุด
  }),

  // แว่นขยาย: วาง/ลากจุดได้ผ่านแว่นขยายเท่านั้น
  // ระหว่างวาง นิ้วขยับ 1 px จอ = จุดขยับ 1/scale px ภาพ (ต้อง ≤ 0.5 ตามข้อกำหนด)
  loupe: Object.freeze({
    sizePx: 180,                 // เส้นผ่านศูนย์กลาง (CSS px)
    magnify: 4,                  // ขยายเทียบภาพหลัก
    minScreenPxPerImagePx: 4,    // อย่างน้อย 4 px จอ ต่อ 1 px ภาพ (=0.25 px ภาพต่อ px จอ) ห้ามต่ำกว่า 2
    maxScreenPxPerImagePx: 10,   // ไม่ขยายเกินนี้ (เท่ากับซูมสูงสุดของภาพหลัก) เพื่อให้ยังเห็นบริเวณรอบจุด
  }),

  marks: Object.freeze({
    count: 4,
    colors: Object.freeze(['#ff5252', '#ffd400', '#3ddc84', '#3fb6ff']),   // จุด 1–4
    hitRadiusPx: 22,             // แตะห่างจากจุดไม่เกินนี้ = แตะโดนจุด
    undoLimit: 200,
  }),

  // ตรวจการกระจายของจุด (เตือน ไม่บล็อก) — ปรับได้
  quality: Object.freeze({
    minHullAreaFraction: 0.05,   // พื้นที่ convex hull < 5% ของกรอบ box_xyxy (เอกซเรย์) / วงกลม (ฟลู) -> เตือน
    collinearMinAngleDeg: 15,    // มุมภายในที่เล็กสุดของ hull < ค่านี้ -> ถือว่าเกือบแนวเดียวกัน -> เตือน
  }),

  timing: Object.freeze({
    idleCutoffSec: 120,          // ไม่มีการแตะ/ขยับเกินนี้ -> หยุดนับเวลา (กันลืมเปิดทิ้งไว้)
  }),

  // ข้อมูลห้ามหาย
  backup: Object.freeze({
    everyNTasks: 10,             // ทำเสร็จครบทุก 10 งาน -> บังคับสำรอง
    maxSnoozes: 1,               // "เลื่อนไปก่อน" ได้ไม่เกิน 1 ครั้ง
  }),
});
