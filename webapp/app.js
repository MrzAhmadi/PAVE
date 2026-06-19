'use strict';

const state = {
  rows:     [],
  filtered: [],
  page:     0,
  pageSize: 50,
  sortCol:  null,
  sortDir:  'asc',
  charts:   {},
  filters: {
    protocol:    '',
    country:     '',
    status:      '',
    datacenter:  '',
    blacklisted: '',
    proxy:       '',
    search:      '',
  },
};

const $ = id => document.getElementById(id);

function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

const toBool = v => String(v).toLowerCase() === 'true';

function normaliseRow(r) {
  r.is_redirecting = toBool(r.is_redirecting);
  r.is_datacenter  = toBool(r.is_datacenter);
  r.is_blacklisted = toBool(r.is_blacklisted);
  r.proxy_detected = toBool(r.proxy_detected);
  r.ipv6_leak      = toBool(r.ipv6_leak);
  r.dns_leak       = toBool(r.dns_leak);
  r.latency_ms     = r.latency_ms !== '' && r.latency_ms != null
                       ? parseFloat(r.latency_ms) : null;
  return r;
}

const PROTO_COLORS = {
  vmess:     '#3b82f6',
  vless:     '#8b5cf6',
  trojan:    '#ec4899',
  ss:        '#10b981',
  hysteria2: '#ef4444',
  hysteria:  '#f59e0b',
  tuic:      '#f97316',
};

const protoColor = p => PROTO_COLORS[(p ?? '').toLowerCase()] ?? '#6b7280';

function countryFlag(code) {
  if (!code || code.length !== 2) return '';
  try {
    return String.fromCodePoint(
      ...code.toUpperCase().split('').map(c => 0x1f1e6 + c.charCodeAt(0) - 65)
    );
  } catch { return ''; }
}

function latClass(ms) {
  if (ms == null || isNaN(ms)) return 'dim';
  if (ms < 300)  return 'lat-fast';
  if (ms < 600)  return 'lat-ok';
  if (ms < 1000) return 'lat-slow';
  return 'lat-bad';
}

function showProgress(visible, pct = 0, text = '') {
  $('progress-bar-wrap').classList.toggle('hidden', !visible);
  $('progress-bar').style.width = pct + '%';
  $('progress-text').textContent = text;
}

function loadFromUrl(url) {
  url = url || $('data-url').value.trim();
  if (!url) return;
  $('load-status').textContent = 'Connecting…';
  showProgress(true, 0, 'Fetching CSV…');
  beginParse();

  const protocols = new Set(), countries = new Set();
  let chunks = 0;

  Papa.parse(url, {
    download: true,
    header: true,
    dynamicTyping: false,
    skipEmptyLines: true,
    chunk(results) {
      ingestChunk(results.data, protocols, countries);
      showProgress(true, Math.min(90, ++chunks * 7),
        `Parsed ${state.rows.length.toLocaleString()} rows…`);
    },
    complete() { finishLoad(protocols, countries); },
    error(err)  { onLoadError(err); },
  });
}

function loadFromFile(file) {
  $('load-status').textContent = `Reading ${file.name}…`;
  showProgress(true, 0, 'Reading file…');
  beginParse();

  const protocols = new Set(), countries = new Set();
  let chunks = 0;

  Papa.parse(file, {
    header: true,
    dynamicTyping: false,
    skipEmptyLines: true,
    chunk(results) {
      ingestChunk(results.data, protocols, countries);
      showProgress(true, Math.min(90, ++chunks * 7),
        `Parsed ${state.rows.length.toLocaleString()} rows…`);
    },
    complete() { finishLoad(protocols, countries); },
    error(err)  { onLoadError(err); },
  });
}

function beginParse() {
  state.rows = [];
  state.filtered = [];
  state.page = 0;
  clearFiltersUI();
  $('dashboard').classList.add('hidden');
  $('empty-state').classList.remove('hidden');
}

function ingestChunk(data, protocols, countries) {
  for (const r of data) {
    normaliseRow(r);
    state.rows.push(r);
    if (r.protocol) protocols.add(r.protocol);
    if (r.country)  countries.add(r.country);
  }
}

function finishLoad(protocols, countries) {
  const n = state.rows.length;
  showProgress(true, 100, `Loaded ${n.toLocaleString()} configs`);
  $('load-status').textContent = `${n.toLocaleString()} configs`;

  populateSelect('f-protocol', [...protocols].sort());
  populateSelect('f-country',  [...countries].sort());

  applyFilters();
  $('empty-state').classList.add('hidden');
  $('dashboard').classList.remove('hidden');
  setTimeout(() => showProgress(false), 800);
}

function onLoadError(err) {
  const isProgressEvent = err instanceof ProgressEvent || String(err) === '[object ProgressEvent]';
  const isFileProtocol  = window.location.protocol === 'file:';
  const msg = isProgressEvent && isFileProtocol
    ? 'Opened via file:// — run: python3 -m http.server 8000 from project root, then open http://localhost:8000/webapp/'
    : isProgressEvent
      ? 'Network error — check the URL and try again, or use Upload'
      : (err?.message ?? String(err));
  $('load-status').textContent = 'Error';
  showProgress(true, 0, msg);
  console.error('[ConfigProbe]', err);
}

function populateSelect(id, values) {
  const sel = $(id);
  sel.innerHTML = '<option value="">All</option>';
  for (const v of values) {
    const o = document.createElement('option');
    o.value = v;
    o.textContent = v;
    sel.appendChild(o);
  }
}

function clearFiltersUI() {
  Object.keys(state.filters).forEach(k => (state.filters[k] = ''));
  ['f-protocol','f-country','f-status','f-datacenter','f-blacklisted','f-proxy']
    .forEach(id => $(id).value = '');
  $('f-search').value = '';
}

function applyFilters() {
  const f = state.filters;
  const q = f.search.toLowerCase().trim();

  state.filtered = state.rows.filter(r => {
    if (f.protocol && r.protocol !== f.protocol) return false;
    if (f.country) {
      if (r.is_redirecting && r.country !== f.country) return false;
    }
    if (f.status === 'working' && !r.is_redirecting)   return false;
    if (f.status === 'failed'  &&  r.is_redirecting)   return false;
    if (f.datacenter  === 'true'  && !r.is_datacenter) return false;
    if (f.datacenter  === 'false' &&  r.is_datacenter) return false;
    if (f.blacklisted === 'true'  && !r.is_blacklisted) return false;
    if (f.blacklisted === 'false' &&  r.is_blacklisted) return false;
    if (f.proxy === 'true'  && !r.proxy_detected)      return false;
    if (f.proxy === 'false' &&  r.proxy_detected)       return false;
    if (q) {
      const hay = [r.server, r.name, r.org, r.asn, r.exit_ip,
                   r.country, r.city, r.error, r.config_id]
        .filter(Boolean).join(' ').toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  state.page = 0;
  if (state.sortCol) doSort();
  renderStats();
  renderCharts();
  renderTable();
}

function doSort() {
  const col = state.sortCol;
  const dir = state.sortDir === 'asc' ? 1 : -1;
  const INF = dir > 0 ? Infinity : -Infinity;

  state.filtered.sort((a, b) => {
    let av = a[col], bv = b[col];
    if (av == null || av === '') av = INF;
    if (bv == null || bv === '') bv = INF;
    if (typeof av === 'boolean') av = av ? 1 : 0;
    if (typeof bv === 'boolean') bv = bv ? 1 : 0;
    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir;
    return String(av).localeCompare(String(bv)) * dir;
  });
}

function renderStats() {
  const globalTotal   = state.rows.length;
  const globalWorking = state.rows.filter(r => r.is_redirecting).length;

  const filtWorking = state.filtered.filter(r => r.is_redirecting);
  const wn  = filtWorking.length;
  const dc  = filtWorking.filter(r => r.is_datacenter).length;
  const bl  = filtWorking.filter(r => r.is_blacklisted).length;
  const lats = filtWorking.map(r => r.latency_ms).filter(v => v != null && !isNaN(v));
  const avgLat = lats.length
    ? (lats.reduce((a, b) => a + b, 0) / lats.length).toFixed(0) + 'ms'
    : '—';

  const pct = (num, den) => den ? (num / den * 100).toFixed(1) + '%' : '—';

  const cards = [
    { label: 'Total Tested',    value: globalTotal.toLocaleString(),          cls: 'c-blue'   },
    { label: 'Working',         value: wn.toLocaleString(),                   cls: 'c-green'  },
    { label: 'Availability',    value: pct(globalWorking, globalTotal),       cls: 'c-teal'   },
    { label: 'Datacenter Exit', value: pct(dc, wn),                          cls: 'c-indigo' },
    { label: 'Blacklisted',     value: pct(bl, wn),                          cls: 'c-red'    },
    { label: 'Avg Latency',     value: avgLat,                               cls: 'c-yellow' },
  ];

  $('stats-grid').innerHTML = cards.map(({ label, value, cls }) => `
    <div class="stat-card">
      <div class="stat-value ${cls}">${value}</div>
      <div class="stat-label">${label}</div>
    </div>
  `).join('');
}

const SCALE_OPTS = {
  x: { ticks: { color: '#64748b' }, grid: { color: '#1b1e2e' } },
  y: { ticks: { color: '#64748b' }, grid: { color: '#1b1e2e' } },
};

function mkChart(id, type, data, extra = {}) {
  state.charts[id]?.destroy();
  state.charts[id] = new Chart($(id), {
    type,
    data,
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#94a3b8', boxWidth: 12, padding: 10 } } },
      ...extra,
    },
  });
}

function renderCharts() {
  const wn = state.filtered.filter(r => r.is_redirecting).length;
  const fn = state.filtered.length - wn;
  mkChart('chart-status', 'doughnut', {
    labels: ['Working', 'Failed'],
    datasets: [{
      data: [wn, fn],
      backgroundColor: ['#10b98199', '#ef444499'],
      borderColor:     ['#10b981',   '#ef4444'],
      borderWidth: 1,
    }],
  }, {
    cutout: '60%',
    plugins: {
      legend: { position: 'bottom', labels: { color: '#94a3b8', padding: 10 } },
    },
  });

  const pCounts = {}, pWork = {};
  for (const r of state.filtered) {
    const p = r.protocol || 'unknown';
    pCounts[p] = (pCounts[p] || 0) + 1;
    if (r.is_redirecting) pWork[p] = (pWork[p] || 0) + 1;
  }
  const pSorted = Object.entries(pCounts).sort((a, b) => b[1] - a[1]).slice(0, 10);
  const pLabels = pSorted.map(([k]) => k);
  mkChart('chart-protocol', 'bar', {
    labels: pLabels,
    datasets: [
      {
        label: 'Total',
        data:  pSorted.map(([k, v]) => v),
        backgroundColor: pLabels.map(l => protoColor(l) + '44'),
        borderColor:     pLabels.map(l => protoColor(l)),
        borderWidth: 1,
      },
      {
        label: 'Working',
        data:  pLabels.map(l => pWork[l] || 0),
        backgroundColor: pLabels.map(l => protoColor(l) + 'bb'),
        borderColor:     pLabels.map(l => protoColor(l)),
        borderWidth: 1,
      },
    ],
  }, { scales: SCALE_OPTS });

  const cCounts = {};
  for (const r of state.filtered) {
    if (r.is_redirecting && r.country) cCounts[r.country] = (cCounts[r.country] || 0) + 1;
  }
  const cSorted = Object.entries(cCounts).sort((a, b) => b[1] - a[1]).slice(0, 15);
  mkChart('chart-country', 'bar', {
    labels: cSorted.map(([k]) => k),
    datasets: [{
      label: 'Working configs',
      data:  cSorted.map(([, v]) => v),
      backgroundColor: '#3b82f666',
      borderColor: '#3b82f6',
      borderWidth: 1,
    }],
  }, {
    indexAxis: 'y',
    scales: {
      x: SCALE_OPTS.x,
      y: { ticks: { color: '#94a3b8', font: { size: 11 } }, grid: { color: '#1b1e2e' } },
    },
    plugins: { legend: { display: false } },
  });
}

function renderTable() {
  const { filtered, page, pageSize } = state;
  const total = filtered.length;
  const start = page * pageSize;
  const end   = Math.min(start + pageSize, total);
  const pages = Math.ceil(total / pageSize) || 1;

  $('table-count').textContent = `${total.toLocaleString()} configs`;
  $('pagination-info').textContent =
    `Page ${page + 1} / ${pages}  (${start + 1}–${end} of ${total.toLocaleString()})`;
  $('btn-prev').disabled = page === 0;
  $('btn-next').disabled = end >= total;

  const frag = document.createDocumentFragment();
  for (const r of filtered.slice(start, end)) {
    const tr = document.createElement('tr');
    tr.innerHTML = rowHTML(r);
    tr.addEventListener('click', () => openDialog(r));
    frag.appendChild(tr);
  }
  const tbody = $('table-body');
  tbody.innerHTML = '';
  tbody.appendChild(frag);

  document.querySelectorAll('th.sortable').forEach(th => {
    th.classList.remove('sort-asc', 'sort-desc');
    if (th.dataset.col === state.sortCol)
      th.classList.add(state.sortDir === 'asc' ? 'sort-asc' : 'sort-desc');
  });
}

function boolBadge(val, yesCls, noCls = 'gray') {
  return val
    ? `<span class="badge badge-${yesCls}">Yes</span>`
    : `<span class="badge badge-${noCls}">No</span>`;
}

function rowHTML(r) {
  const c   = protoColor(r.protocol);
  const proto = r.protocol
    ? `<span class="badge" style="background:${c}22;color:${c};border:1px solid ${c}55">${esc(r.protocol)}</span>`
    : '<span class="dim">—</span>';

  const latency = r.latency_ms != null
    ? `<span class="${latClass(r.latency_ms)}">${r.latency_ms.toFixed(0)}ms</span>`
    : '<span class="dim">—</span>';

  const status = r.is_redirecting
    ? '<span class="badge badge-green">✓ Working</span>'
    : '<span class="badge badge-red">✗ Failed</span>';

  const country = r.country
    ? `${countryFlag(r.country_code)} ${esc(r.country)}`
    : '<span class="dim">—</span>';

  const name = r.name
    ? `<span class="trunc" style="max-width:160px" title="${esc(r.name)}">${esc(r.name)}</span>`
    : '<span class="dim">—</span>';

  const org = r.org
    ? `<span class="trunc dim" style="max-width:180px;font-size:12px" title="${esc(r.org)}">${esc(r.org)}</span>`
    : '<span class="dim">—</span>';

  const error = r.error
    ? `<span class="trunc" style="max-width:180px;font-size:12px;color:#f87171" title="${esc(r.error)}">${esc(r.error)}</span>`
    : '<span class="dim">—</span>';

  return `
    <td>${proto}</td>
    <td class="mono" style="font-size:12px;color:#94a3b8">${esc(r.server)}:${esc(r.port)}</td>
    <td>${name}</td>
    <td style="font-size:12px">${country}</td>
    <td>${latency}</td>
    <td>${status}</td>
    <td>${boolBadge(r.is_datacenter,  'indigo')}</td>
    <td>${boolBadge(r.is_blacklisted, 'red')}</td>
    <td>${boolBadge(r.proxy_detected, 'orange')}</td>
    <td>${org}</td>
    <td>${error}</td>
  `;
}

let activeConfig = null;

function openDialog(r) {
  activeConfig = r;
  const c = protoColor(r.protocol);

  $('dialog-heading').innerHTML = `
    <div class="dialog-proto-row">
      <span class="badge" style="background:${c}22;color:${c};border:1px solid ${c}55;font-size:13px;padding:3px 10px">
        ${esc(r.protocol || '?')}
      </span>
      <span class="dialog-server">${esc(r.server)}:${esc(r.port)}</span>
      ${r.is_redirecting
        ? '<span class="badge badge-green">✓ Working</span>'
        : '<span class="badge badge-red">✗ Failed</span>'}
    </div>
    ${r.name ? `<div class="dialog-name">${esc(r.name)}</div>` : ''}
  `;

  const field = (label, value, cls = '') =>
    value != null && value !== '' && value !== 'False' && value !== false
      ? `<div class="detail-field${cls ? ' ' + cls : ''}">
           <div class="detail-label">${label}</div>
           <div class="detail-value${cls.includes('full') ? '' : ''}">${value}</div>
         </div>`
      : `<div class="detail-field${cls ? ' ' + cls : ''}">
           <div class="detail-label">${label}</div>
           <div class="detail-value dim">—</div>
         </div>`;

  const monoField = (label, value, cls = '') =>
    `<div class="detail-field${cls ? ' ' + cls : ''}">
       <div class="detail-label">${label}</div>
       <div class="detail-value mono">${value != null && value !== '' ? esc(value) : '<span class="dim">—</span>'}</div>
     </div>`;

  const boolField = (label, val, yesColor = 'red', noColor = 'gray') =>
    `<div class="detail-field">
       <div class="detail-label">${label}</div>
       <div class="detail-value">
         ${val
           ? `<span class="badge badge-${yesColor}">Yes</span>`
           : `<span class="badge badge-${noColor}">No</span>`}
       </div>
     </div>`;

  const latency = r.latency_ms != null
    ? `<span class="${latClass(r.latency_ms)}">${r.latency_ms.toFixed(0)} ms</span>`
    : '<span class="dim">—</span>';

  const countryDisplay = r.country
    ? `${countryFlag(r.country_code)} ${esc(r.country)}${r.city ? `, ${esc(r.city)}` : ''}`
    : '—';

  $('dialog-body').innerHTML = `
    ${r.raw_config ? `
    <div class="detail-section">
      <div class="detail-section-title">Config URI</div>
      <div class="raw-config-box">
        <span class="raw-config-text" id="raw-config-text">${esc(r.raw_config)}</span>
        <button class="raw-copy-btn" onclick="copyRawConfig()" title="Copy URI">📋</button>
      </div>
    </div>
    <hr class="dialog-divider">` : ''}

    <div class="detail-section">
      <div class="detail-section-title">Connection</div>
      <div class="detail-grid">
        ${monoField('Server', r.server)}
        ${monoField('Port', r.port)}
        ${monoField('Config ID', r.config_id, 'full')}
        ${field('Source', r.source ? esc(r.source) : null, 'full')}
        ${field('Tested at', r.timestamp ? esc(r.timestamp.replace('T', ' ').split('.')[0]) : null, 'full')}
      </div>
    </div>

    <hr class="dialog-divider">

    <div class="detail-section">
      <div class="detail-section-title">Exit Node</div>
      <div class="detail-grid">
        ${monoField('Exit IP', r.exit_ip)}
        ${monoField('IPv6 Exit IP', r.ipv6_exit_ip || null)}
        <div class="detail-field full">
          <div class="detail-label">Country / City</div>
          <div class="detail-value">${countryDisplay}</div>
        </div>
        ${field('ISP / Org', r.org ? esc(r.org) : null, 'full')}
        ${monoField('ASN', r.asn)}
      </div>
    </div>

    <hr class="dialog-divider">

    <div class="detail-section">
      <div class="detail-section-title">Performance</div>
      <div class="detail-grid">
        <div class="detail-field">
          <div class="detail-label">Latency</div>
          <div class="detail-value" style="font-size:18px;font-weight:700">${latency}</div>
        </div>
        ${monoField('Local IP', r.local_ip || null)}
      </div>
    </div>

    <hr class="dialog-divider">

    <div class="detail-section">
      <div class="detail-section-title">Security Flags</div>
      <div class="detail-grid">
        ${boolField('Datacenter / Hosting', r.is_datacenter,  'indigo', 'gray')}
        ${boolField('Blacklisted IP',       r.is_blacklisted, 'red',    'gray')}
        ${boolField('Proxy Detected',       r.proxy_detected, 'orange', 'gray')}
        ${boolField('IPv6 Leak',            r.ipv6_leak,      'red',    'green')}
        ${boolField('DNS Leak',             r.dns_leak,       'red',    'green')}
      </div>
    </div>

    ${r.error ? `
    <hr class="dialog-divider">
    <div class="detail-section">
      <div class="detail-section-title">Error</div>
      <div style="color:#f87171;font-size:13px;font-family:var(--mono)">${esc(r.error)}</div>
    </div>` : ''}
  `;

  $('dialog-overlay').classList.remove('hidden');
  document.addEventListener('keydown', onDialogKey);
}

function closeDialog() {
  $('dialog-overlay').classList.add('hidden');
  document.removeEventListener('keydown', onDialogKey);
  activeConfig = null;
}

function onDialogKey(e) {
  if (e.key === 'Escape') closeDialog();
}

function copyRawConfig() {
  if (!activeConfig?.raw_config) { showToast('No URI available'); return; }
  writeClipboard(activeConfig.raw_config, 'URI copied!');
}

function copyConfigDetails() {
  if (!activeConfig) return;
  const r = activeConfig;
  const lines = [
    `ConfigProbe Result`,
    `─────────────────────────────`,
    `Protocol : ${r.protocol || '—'}`,
    `Server   : ${r.server}:${r.port}`,
    `Name     : ${r.name || '—'}`,
    `Config ID: ${r.config_id}`,
    ``,
    `Status   : ${r.is_redirecting ? 'Working' : 'Failed'}`,
    `Latency  : ${r.latency_ms != null ? r.latency_ms.toFixed(0) + 'ms' : '—'}`,
    ``,
    `Exit IP  : ${r.exit_ip || '—'}`,
    `Country  : ${r.country || '—'}${r.city ? ', ' + r.city : ''}`,
    `ISP/Org  : ${r.org || '—'}`,
    `ASN      : ${r.asn || '—'}`,
    ``,
    `Datacenter    : ${r.is_datacenter  ? 'Yes' : 'No'}`,
    `Blacklisted   : ${r.is_blacklisted ? 'Yes' : 'No'}`,
    `Proxy Detected: ${r.proxy_detected ? 'Yes' : 'No'}`,
    `IPv6 Leak     : ${r.ipv6_leak      ? 'Yes' : 'No'}`,
    r.error ? `\nError: ${r.error}` : '',
  ].filter(l => l !== undefined).join('\n');

  writeClipboard(lines, 'Copied to clipboard!');
}

function writeClipboard(text, toast = 'Copied!') {
  const fallback = () => {
    const ta = Object.assign(document.createElement('textarea'), { value: text });
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    ta.remove();
    showToast(toast);
  };
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(() => showToast(toast)).catch(fallback);
  } else {
    fallback();
  }
}

function showToast(msg) {
  let toast = document.querySelector('.copy-toast');
  if (!toast) {
    toast = Object.assign(document.createElement('div'), { className: 'copy-toast' });
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.classList.add('show');
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => toast.classList.remove('show'), 2200);
}

function exportCSV() {
  const csv  = Papa.unparse(state.filtered);
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url  = URL.createObjectURL(blob);
  const a    = Object.assign(document.createElement('a'), {
    href: url, download: 'configprobe_filtered.csv',
  });
  a.click();
  URL.revokeObjectURL(url);
}

document.addEventListener('DOMContentLoaded', () => {
  $('btn-load-url').addEventListener('click',   () => loadFromUrl());
  $('btn-load-url-2').addEventListener('click', () => loadFromUrl());
  $('data-url').addEventListener('keydown', e => { if (e.key === 'Enter') loadFromUrl(); });
  $('file-input').addEventListener('change', e => {
    if (e.target.files[0]) loadFromFile(e.target.files[0]);
  });

  const FILTER_MAP = {
    'f-protocol':    'protocol',
    'f-country':     'country',
    'f-status':      'status',
    'f-datacenter':  'datacenter',
    'f-blacklisted': 'blacklisted',
    'f-proxy':       'proxy',
  };
  Object.entries(FILTER_MAP).forEach(([id, key]) => {
    $(id).addEventListener('change', e => {
      state.filters[key] = e.target.value;
      applyFilters();
    });
  });

  let searchTimer;
  $('f-search').addEventListener('input', e => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.filters.search = e.target.value;
      applyFilters();
    }, 300);
  });

  $('btn-reset-filters').addEventListener('click', () => {
    clearFiltersUI();
    applyFilters();
  });

  $('dialog-close').addEventListener('click', closeDialog);
  $('dialog-close-btn').addEventListener('click', closeDialog);
  $('btn-copy-uri').addEventListener('click', copyRawConfig);
  $('btn-copy-config').addEventListener('click', copyConfigDetails);
  $('dialog-overlay').addEventListener('click', e => {
    if (e.target === $('dialog-overlay')) closeDialog();
  });

  $('btn-export').addEventListener('click', exportCSV);

  $('page-size').addEventListener('change', e => {
    state.pageSize = parseInt(e.target.value, 10);
    state.page = 0;
    renderTable();
  });

  $('btn-prev').addEventListener('click', () => {
    state.page--;
    renderTable();
    document.querySelector('.table-scroll').scrollTop = 0;
  });
  $('btn-next').addEventListener('click', () => {
    state.page++;
    renderTable();
    document.querySelector('.table-scroll').scrollTop = 0;
  });

  document.querySelectorAll('th.sortable').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.col;
      state.sortDir = (state.sortCol === col && state.sortDir === 'asc') ? 'desc' : 'asc';
      state.sortCol = col;
      state.page = 0;
      doSort();
      renderTable();
    });
  });

  const defaultUrl = window.location.pathname.includes('/webapp/')
    ? '../results/merged/results.csv'
    : 'results/merged/results.csv';
  $('data-url').value = defaultUrl;
  loadFromUrl(defaultUrl);
});
