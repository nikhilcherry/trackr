function fmtDuration(start, end) {
  const endTs = end || (Date.now() / 1000);
  let secs = Math.floor(endTs - start);
  const h = Math.floor(secs / 3600); secs %= 3600;
  const m = Math.floor(secs / 60); secs %= 60;
  if (h) return `${h}h${m}m`;
  if (m) return `${m}m${secs}s`;
  return `${secs}s`;
}

function fmtTime(ts) {
  return new Date(ts * 1000).toLocaleString();
}

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`request failed: ${url}`);
  return res.json();
}

async function renderRunsTable() {
  const runs = await fetchJSON('/api/runs');
  const projects = [...new Set(runs.map(r => r.project))].sort();
  const select = document.getElementById('project-filter');
  for (const p of projects) {
    const opt = document.createElement('option');
    opt.value = p;
    opt.textContent = p;
    select.appendChild(opt);
  }
  select.addEventListener('change', () => paintRuns(runs, select.value));
  paintRuns(runs, '');
}

function paintRuns(runs, project) {
  const tbody = document.querySelector('#runs-table tbody');
  tbody.innerHTML = '';
  const filtered = project ? runs.filter(r => r.project === project) : runs;
  for (const r of filtered) {
    const tr = document.createElement('tr');
    const metricsStr = Object.entries(r.final_metrics || {})
      .map(([k, v]) => `${k}=${Number(v).toPrecision(4)}`).join(', ');
    tr.innerHTML = `
      <td><a href="/run/${encodeURIComponent(r.id)}">${r.id}</a></td>
      <td>${r.project}</td>
      <td>${r.name}</td>
      <td><span class="status status-${r.status}">${r.status}</span></td>
      <td>${fmtTime(r.start_time)}</td>
      <td>${fmtDuration(r.start_time, r.end_time)}</td>
      <td>${metricsStr}</td>
    `;
    tbody.appendChild(tr);
  }
}

function runIdFromPath() {
  const parts = window.location.pathname.split('/');
  return decodeURIComponent(parts[parts.length - 1]);
}

async function renderRunDetail() {
  const runId = runIdFromPath();
  const [run, metrics, artifacts] = await Promise.all([
    fetchJSON(`/api/runs/${encodeURIComponent(runId)}`),
    fetchJSON(`/api/runs/${encodeURIComponent(runId)}/metrics`),
    fetchJSON(`/api/runs/${encodeURIComponent(runId)}/artifacts`),
  ]);

  document.getElementById('run-title').textContent = `${run.project} / ${run.name}`;
  document.getElementById('run-meta').innerHTML = `
    <p><strong>ID:</strong> ${run.id}</p>
    <p><strong>Status:</strong> <span class="status status-${run.status}">${run.status}</span></p>
    <p><strong>Started:</strong> ${fmtTime(run.start_time)}</p>
    <p><strong>Duration:</strong> ${fmtDuration(run.start_time, run.end_time)}</p>
    <p><strong>Git commit:</strong> ${run.git_commit || '-'}</p>
  `;
  document.getElementById('config').textContent = JSON.stringify(run.config, null, 2);

  const byKey = {};
  for (const m of metrics) {
    (byKey[m.key] = byKey[m.key] || []).push(m);
  }
  const chartsDiv = document.getElementById('charts');
  const keys = Object.keys(byKey);
  if (keys.length === 0) {
    chartsDiv.textContent = 'No metrics logged.';
  }
  for (const key of keys) {
    const points = byKey[key];
    const wrap = document.createElement('div');
    wrap.className = 'chart-wrap';
    const label = document.createElement('div');
    label.className = 'chart-label';
    label.textContent = key;
    const canvas = document.createElement('canvas');
    canvas.width = 640;
    canvas.height = 220;
    wrap.appendChild(label);
    wrap.appendChild(canvas);
    chartsDiv.appendChild(wrap);
    drawLineChart(canvas, points.map(p => [p.step, p.value]));
  }

  const artifactsDiv = document.getElementById('artifacts');
  if (artifacts.length === 0) {
    artifactsDiv.textContent = 'No artifacts.';
  }
  const imageExts = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'];
  for (const a of artifacts) {
    // The URL must reference the actual on-disk filename (path's basename,
    // which trackr disambiguates per-artifact so repeated log_artifact()
    // calls with the same original_name don't collide) -- not
    // original_name, which two rows can legitimately share.
    const onDiskName = a.path.split('/').pop();
    const url = `/api/artifacts/${encodeURIComponent(run.id)}/${encodeURIComponent(onDiskName)}`;
    const item = document.createElement('div');
    item.className = 'artifact-item';
    const isImage = imageExts.some(ext => a.original_name.toLowerCase().endsWith(ext));
    if (isImage) {
      item.innerHTML = `<a href="${url}" target="_blank"><img src="${url}" alt="${a.original_name}"></a><div>${a.original_name}</div>`;
    } else {
      item.innerHTML = `<a href="${url}" target="_blank">${a.original_name}</a>`;
    }
    artifactsDiv.appendChild(item);
  }
}

function drawLineChart(canvas, points) {
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height, pad = 30;
  ctx.clearRect(0, 0, w, h);
  if (points.length === 0) return;
  const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
  const xMin = Math.min(...xs), xMax = Math.max(...xs);
  const yMin = Math.min(...ys), yMax = Math.max(...ys);
  const xRange = xMax - xMin || 1;
  const yRange = yMax - yMin || 1;

  const toX = x => pad + ((x - xMin) / xRange) * (w - 2 * pad);
  const toY = y => h - pad - ((y - yMin) / yRange) * (h - 2 * pad);

  ctx.strokeStyle = '#ccc';
  ctx.beginPath();
  ctx.moveTo(pad, h - pad);
  ctx.lineTo(w - pad, h - pad);
  ctx.moveTo(pad, pad);
  ctx.lineTo(pad, h - pad);
  ctx.stroke();

  ctx.strokeStyle = '#3366cc';
  ctx.lineWidth = 2;
  ctx.beginPath();
  points.forEach(([x, y], i) => {
    const px = toX(x), py = toY(y);
    if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
  });
  ctx.stroke();

  ctx.fillStyle = '#555';
  ctx.font = '11px sans-serif';
  ctx.fillText(yMax.toPrecision(4), 2, pad + 4);
  ctx.fillText(yMin.toPrecision(4), 2, h - pad + 4);
  ctx.fillText(String(xMin), pad, h - pad + 14);
  ctx.fillText(String(xMax), w - pad - 20, h - pad + 14);
}
