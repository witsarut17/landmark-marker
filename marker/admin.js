// หน้าทีมวิจัย: เข้าสู่ระบบ → ดูความคืบหน้า → ดาวน์โหลด JSON/CSV (ใช้ Exporter ตัวเดียวกับหน้าเว็บมาร์กจุด)
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const timeTH = (iso) => (iso ? new Date(iso).toLocaleString('th-TH', { dateStyle: 'medium', timeStyle: 'short' }) : '—');

  async function api(path, opts = {}) {
    const r = await fetch(path, Object.assign({
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'pelnav' },
    }, opts));
    let body = null;
    try { body = await r.json(); } catch (_) { /* ไม่ใช่ JSON */ }
    if (!r.ok) { const e = new Error((body && body.error) || `HTTP ${r.status}`); e.status = r.status; throw e; }
    return body;
  }

  function show(which) {
    $('loginCard').hidden = which !== 'login';
    $('overviewCard').hidden = which !== 'overview';
    $('btnLogout').hidden = which === 'login';
  }

  async function start() {
    $('pageErr').textContent = '';
    try {
      const me = await api('/api/me');
      if (me.role !== 'team') {
        $('who').textContent = `เข้าสู่ระบบเป็น ${me.username} (แพทย์) — หน้านี้สำหรับทีมวิจัยเท่านั้น`;
        show('none');
        return;
      }
      $('who').textContent = `เข้าสู่ระบบเป็น ${me.username} (ทีมวิจัย)`;
      await overview();
    } catch (e) {
      if (e.status === 401) { show('login'); return; }
      $('pageErr').textContent = `ติดต่อเซิร์ฟเวอร์ไม่ได้: ${e.message}`;
    }
  }

  async function overview() {
    const d = await api('/api/admin/overview');
    $('backupInfo').textContent = `สำรองฐานข้อมูลล่าสุด: ${d.last_backup ? timeTH(d.last_backup) : 'ยังไม่มี'}`;
    const tb = $('rows');
    tb.innerHTML = '';
    for (const r of d.doctors) {
      const tr = document.createElement('tr');
      const cells = [r.username, r.package_id, `${r.done}/${r.total}`, String(r.skipped), timeTH(r.last_saved)];
      cells.forEach((c, i) => { const td = document.createElement('td'); td.textContent = c; if (i >= 2 && i <= 3) td.className = 'num'; tr.append(td); });
      const td = document.createElement('td');
      for (const kind of ['JSON', 'CSV']) {
        const b = document.createElement('button');
        b.className = 'btn btn-small';
        b.textContent = kind;
        b.dataset.kind = kind;
        b.dataset.user = r.username;
        b.dataset.pkg = r.package_id;
        b.addEventListener('click', () => download(r.username, r.package_id, kind));
        td.append(b, ' ');
      }
      tr.append(td);
      tb.append(tr);
    }
    if (!d.doctors.length) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 6;
      td.textContent = 'ยังไม่มีแพทย์ที่กำหนดแพ็กเกจ (ใช้คำสั่ง add-user และ assign)';
      tr.append(td);
      tb.append(tr);
    }
    show('overview');
  }

  async function download(user, pkg, kind) {
    try {
      const d = await api(`/api/admin/data?user=${encodeURIComponent(user)}&package=${encodeURIComponent(pkg)}`);
      const ctx = { package_id: d.package_id, app_version: 'server', total_tasks: d.items.length,
        current_index: d.current_index, tasks: d.tasks, items: d.items };
      const done = Exporter.countFinal(d.tasks);
      if (kind === 'JSON') Exporter.download(Exporter.buildJSON(ctx), `${user}_${Exporter.jsonFilename(pkg, done, d.items.length)}`, 'application/json');
      else Exporter.download(Exporter.buildCSV(ctx), `${user}_${Exporter.csvFilename(pkg)}`, 'text/csv');
    } catch (e) {
      $('pageErr').textContent = `ดาวน์โหลดไม่ได้: ${e.message}`;
    }
  }

  $('loginForm').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    $('loginErr').textContent = '';
    try {
      await api('/api/login', { method: 'POST', body: JSON.stringify({ username: $('username').value, password: $('password').value }) });
      $('password').value = '';
      await start();
    } catch (e) {
      $('loginErr').textContent = e.message;
    }
  });
  $('btnLogout').addEventListener('click', async () => {
    try { await api('/api/logout', { method: 'POST' }); } catch (_) { /* ignore */ }
    $('who').textContent = '';
    show('login');
  });
  $('btnRefresh').addEventListener('click', () => overview().catch((e) => { $('pageErr').textContent = e.message; }));
  start();
})();
