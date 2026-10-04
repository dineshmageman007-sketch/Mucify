// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 mageman007 and contributors
// Every write request carries a header the backend requires (blocks other web pages from calling it).
(function () {
  const _fetch = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    init.headers = Object.assign({}, init.headers || {}, { 'X-Mucify': '1' });
    return _fetch(input, init);
  };
})();

// External links open in the user's real browser, not inside the app window.
document.addEventListener('click', e => {
  const a = e.target.closest('a[data-ext]');
  if (!a) return;
  e.preventDefault();
  openUrl(a.getAttribute('href'));
});
async function openUrl(url) {
  await fetch('/api/open-url', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }) });
}
async function postJSON(url, body) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  let data = {}; try { data = await r.json(); } catch (_) {}
  return { status: r.status, ok: r.ok, data };
}
const $ = id => document.getElementById(id);

// ============================================================
// VIEW ROUTING
// ============================================================
let currentView = 'landing';
function showView(name) {
  currentView = name;
  document.querySelectorAll('.view').forEach(v => v.classList.add('hidden'));
  document.getElementById('view-' + name).classList.remove('hidden');
  document.querySelectorAll('[data-nav]').forEach(b => {
    const on = b.dataset.nav === name;
    b.classList.toggle('active', on);
    if (on) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  });
  const scroller = document.querySelector('.content'); if (scroller) scroller.scrollTop = 0;
  if (name === 'playlist') { refreshLibraryStatus(); refreshSources(); }
  loadRecent();
  if (name === 'guide') loadGuide();
}
function showSettings() {
  loadSettings();
  showView('settings');
}

// ============================================================
// SETTINGS
// ============================================================
let currentCfg = null;
async function loadSettings() {
  const cfg = await (await fetch('/api/settings')).json();
  currentCfg = cfg;
  $('cfg-qobuz-app_id').value = cfg.qobuz.app_id || '';
  $('cfg-qobuz-user_id').value = cfg.qobuz.user_id || '';
  $('cfg-soulseek-username').value = cfg.soulseek.username || '';
  $('cfg-soulseek-password').value = cfg.soulseek.password || '';
  $('cfg-paths-sldl_exe').value = cfg.paths.sldl_exe || '';
  $('cfg-paths-rsgain_exe').value = cfg.paths.rsgain_exe || '';
  $('cfg-paths-music_vault').value = cfg.paths.music_vault || '';
  $('cfg-paths-working_dir').value = cfg.paths.working_dir || '';
  const d = cfg.detected || {};
  $('tool-detect-status').innerHTML =
    `<div>${d.sldl_exe ? '✅ Downloader (sldl) ready' : '❌ Downloader (sldl) is missing. Please reinstall Mucify.'}</div>` +
    `<div>${d.rsgain_exe ? '✅ ReplayGain tool (rsgain) ready' : '❌ ReplayGain tool (rsgain) is missing. Please reinstall Mucify.'}</div>`;
  renderQobuzState(cfg.qobuz);
  syncBanner(cfg.qobuz);
  bgmSync(cfg.app);
}

function renderQobuzState(q) {
  const el = $('set-qobuz-state');
  if (!el) return;
  if (!q.token) { el.className = 'state-line none'; el.textContent = 'Not connected (optional).'; }
  else if (q.status === 'expired') { el.className = 'state-line bad'; el.textContent = '⚠ Connection expired. Please reconnect.'; }
  else { el.className = 'state-line ok'; el.textContent = '✓ Qobuz connected'; }
  const btn = $('set-qb-connect');
  if (btn) btn.textContent = q.token ? 'Reconnect Qobuz' : 'Connect Qobuz';
  const dis = $('set-qb-disconnect');
  if (dis) dis.classList.toggle('hidden', !q.token);
}

function syncBanner(q) {
  $('qobuz-banner').classList.toggle('hidden', !(q.token && q.status === 'expired'));
}
async function refreshBanner() {
  const cfg = await (await fetch('/api/settings')).json();
  syncBanner(cfg.qobuz);
  return cfg;
}
function reconnectQobuz() {
  showSettings();
  setTimeout(() => qobuzConnect('set'), 150);
}

async function saveSettings() {
  const body = {
    qobuz: { app_id: $('cfg-qobuz-app_id').value.trim(), user_id: $('cfg-qobuz-user_id').value.trim() },
    soulseek: { username: $('cfg-soulseek-username').value.trim(), password: $('cfg-soulseek-password').value },
    paths: {
      sldl_exe: $('cfg-paths-sldl_exe').value.trim(), rsgain_exe: $('cfg-paths-rsgain_exe').value.trim(),
      music_vault: $('cfg-paths-music_vault').value.trim(), working_dir: $('cfg-paths-working_dir').value.trim(),
    },
  };
  await postJSON('/api/settings', body);
  const status = $('settings-status');
  status.textContent = 'Saved ✓';
  setTimeout(() => status.textContent = '', 2000);
  loadSettings();
}

function resetFolders() {
  if (!currentCfg) return;
  $('cfg-paths-music_vault').value = currentCfg.defaults.music_vault;
  $('cfg-paths-working_dir').value = currentCfg.defaults.working_dir;
}
async function openFolderFrom(inputId) {
  const p = $(inputId).value.trim();
  if (p) openFolder(p);
}
async function openFolder(path) {
  if (!path) return;
  const r = await postJSON('/api/open-folder', { path });
  if (!r.ok) alert(r.data.error || 'Folder not found yet.');
}
async function exportFile(path, filename) {
  const r = await postJSON('/api/export', filename ? { filename } : { path });
  if (!r.ok) alert(r.data.error || 'Could not save the file.');
}

// ---------------- Soulseek helpers (wizard + settings) ----------------
async function rollCredential(inputId, kind) {
  const d = await (await fetch('/api/random-credential?kind=' + kind)).json();
  $(inputId).value = d.value;
  if (kind === 'password') $(inputId).type = 'text';
}
function togglePw(id) { const i = $(id); i.type = i.type === 'password' ? 'text' : 'password'; }

async function testSoulseek(ctx) {
  const userId = ctx === 'wiz' ? 'wiz-ss-user' : 'cfg-soulseek-username';
  const passId = ctx === 'wiz' ? 'wiz-ss-pass' : 'cfg-soulseek-password';
  const out = $(ctx === 'wiz' ? 'wiz-ss-result' : 'set-ss-result');
  out.className = 'test-result busy'; out.textContent = 'Connecting…';
  const r = await postJSON('/api/soulseek/test', { username: $(userId).value.trim(), password: $(passId).value });
  out.className = 'test-result ' + (r.data.ok ? 'ok' : 'bad');
  out.textContent = (r.data.ok ? '✓ ' : '✗ ') + (r.data.message || 'No answer');
}

// ---------------- Qobuz connect block (wizard + settings) ----------------
const VPN_HTML = 'Qobuz may not be available in your region, so the login page might not load. ' +
  'You only need a VPN to <b>create</b> your Qobuz account in your browser (the <a data-ext href="https://windscribe.com/">Windscribe</a> Chrome extension works well for that). ' +
  'Signing in here afterwards normally needs no VPN. <br><span style="opacity:.8">If this window still won\'t load, a system-wide VPN (like the Windscribe app) covers everything, because a browser extension only affects the browser.</span>';

function qobuzBlockHtml(p) {
  return `
    <p class="note" style="margin-top:0"><b>Heads-up:</b> signing in with Google, Apple or Facebook doesn't work in this window. Create a Qobuz account with an email and password at <a data-ext href="https://qobuz.com/signin" style="color:var(--accent2)">qobuz.com/signin</a> (it opens in your browser), then sign in here with those details. If Qobuz isn't available in your region, turn on a VPN extension such as Windscribe for Chrome <b>only while creating the account</b>. You won't need it to sign in here.</p>
    <div class="qb-actions">
      <button class="btn btn-accent" id="${p}-qb-connect" onclick="qobuzConnect('${p}')">Connect Qobuz</button>
      <button class="btn btn-ghost hidden" id="${p}-qb-disconnect" onclick="qobuzDisconnect('${p}')">Disconnect</button>
    </div>
    <div class="qb-status" id="${p}-qb-status"></div>
    <div class="vpn-hint hidden" id="${p}-qb-vpn">${VPN_HTML}</div>
    <details class="advanced" id="${p}-qb-manual"><summary>Having trouble? Paste the token manually</summary>
      <ol class="manual-steps">
        <li>Open <a data-ext href="https://play.qobuz.com/" style="color:var(--accent2)">play.qobuz.com</a> in Chrome or Edge and sign in.</li>
        <li>Press <b>F12</b> to open Developer Tools and click the <b>Network</b> tab.</li>
        <li>Type <b>api.json</b> in the filter box, then click around the player (open any album) so requests appear.</li>
        <li>Click one of the requests and look under <b>Request Headers</b> for <b>X-User-Auth-Token</b>.</li>
        <li>Copy its value and paste it below.</li>
      </ol>
      <div class="input-wrap"><input id="${p}-qb-token" type="password" placeholder="Paste X-User-Auth-Token here" autocomplete="off" spellcheck="false">
        <button type="button" class="dice" title="Show / hide" onclick="togglePw('${p}-qb-token')">👁</button></div>
      <div class="qb-actions"><button class="btn" onclick="qobuzSaveManual('${p}')">Save token</button></div>
    </details>`;
}

function setQbStatus(p, text, cls) {
  const el = $(p + '-qb-status'); el.textContent = text || ''; el.className = 'qb-status ' + (cls || '');
}
let qbPoll = null;
async function qobuzConnect(p) {
  setQbStatus(p, 'Opening Qobuz…');
  const r = await postJSON('/api/qobuz/connect');
  trackQobuzConnect(p, r.data);
}
function trackQobuzConnect(p, st) {
  clearInterval(qbPoll);
  applyConnectState(p, st);
  if (st.state !== 'waiting') return;
  qbPoll = setInterval(async () => {
    const s = await (await fetch('/api/qobuz/connect/status')).json();
    applyConnectState(p, s);
    if (s.state !== 'waiting') clearInterval(qbPoll);
  }, 1000);
}
function applyConnectState(p, st) {
  $(p + '-qb-vpn').classList.toggle('hidden', !st.vpn_hint && st.state !== 'failed');
  if (st.state === 'waiting') setQbStatus(p, st.message, '');
  else if (st.state === 'connected') { setQbStatus(p, '✓ Qobuz connected', 'ok'); onQobuzConnected(p); }
  else if (st.state === 'failed') { setQbStatus(p, st.message, 'bad'); $(p + '-qb-manual').open = true; }
  else setQbStatus(p, '', '');
}
async function qobuzSaveManual(p) {
  const token = $(p + '-qb-token').value.trim();
  const r = await postJSON('/api/qobuz/token', { token });
  setQbStatus(p, r.data.message || '', r.ok ? 'ok' : 'bad');
  if (r.ok) { $(p + '-qb-token').value = ''; onQobuzConnected(p); }
}
async function qobuzDisconnect(p) {
  await postJSON('/api/qobuz/disconnect');
  setQbStatus(p, 'Qobuz disconnected.', '');
  onQobuzConnected(p, true);
}
function onQobuzConnected(p, disconnected) {
  if (p === 'wiz') {
    $('wiz-qb-next').classList.toggle('hidden', !!disconnected);
    $('wiz-qb-skip').classList.toggle('hidden', !disconnected);
  } else { loadSettings(); }
  refreshBanner();
}

// ---------------- First-run wizard ----------------
let wizStep = 0, wizInfo = null;
function renderDots() {
  $('wiz-dots').innerHTML = [0, 1, 2, 3, 4].map(i => `<i class="${i <= wizStep ? 'on' : ''}"></i>`).join('');
}
function wizGo(n) {
  wizStep = n;
  document.querySelectorAll('.wiz-step').forEach(el => el.classList.toggle('hidden', Number(el.dataset.step) !== n));
  renderDots();
}
async function wizSoulseekNext() {
  if (!$('wiz-ss-user').value.trim() || !$('wiz-ss-pass').value) {
    $('wiz-ss-result').className = 'test-result bad';
    $('wiz-ss-result').textContent = 'Enter a username and password (or press a 🎲 button).';
    return;
  }
  wizGo(2);
}
async function wizFinish() {
  const btn = $('wiz-finish'); btn.disabled = true;
  const r = await postJSON('/api/setup/complete', { username: $('wiz-ss-user').value.trim(), password: $('wiz-ss-pass').value });
  btn.disabled = false;
  if (!r.ok) { $('wiz-finish-msg').className = 'test-result bad'; $('wiz-finish-msg').textContent = r.data.error || 'Setup failed.'; return; }
  wizGo(4);
}
function wizClose() { $('wizard').classList.add('hidden'); showView('landing'); refreshBanner(); }

async function initApp() {
  $('wiz-qobuz-block').innerHTML = qobuzBlockHtml('wiz');
  $('set-qobuz-block').innerHTML = qobuzBlockHtml('set');
  const info = await (await fetch('/api/setup/state')).json();
  wizInfo = info;
  $('app-version').textContent = 'Mucify ' + info.version;
  $('wiz-music').textContent = info.defaults.music_vault;
  $('wiz-work').textContent = info.defaults.working_dir;
  if (!info.first_run_done) {
    $('wiz-ss-user').value = info.suggested.username;
    $('wiz-ss-pass').value = info.suggested.password;
    $('wiz-ss-pass').type = 'text';
    $('wizard').classList.remove('hidden');
    wizGo(0);
  }
  const cfg = await refreshBanner();
  renderQobuzState(cfg.qobuz);
  bgmSync(cfg.app);
  if (cfg.qobuz.token) {   // quiet background check so an expired token is noticed early
    postJSON('/api/qobuz/validate').then(r => { if (r.data.state === 'expired') refreshBanner(); });
  }
}
window.addEventListener('DOMContentLoaded', initApp);

// ============================================================
// NATIVE BROWSE (used by Settings + Post-Processing folder field)
// ============================================================
async function browseInto(inputId, mode, filetypes) {
  const res = await fetch('/api/browse', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode, filetypes: filetypes || 'any' })
  });
  const data = await res.json();
  if (data.error) { alert(data.error); return; }
  if (data.path) document.getElementById(inputId).value = data.path;
}

// Native browse used by the CSV-driven domains (Playlist Manager / Qobuz / Downloader)
async function browseFiles(prefix) {
  const multi = prefix === 'pm-add';
  const res = await fetch('/api/browse', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: multi ? 'files' : 'file', filetypes: 'csv' })
  });
  const data = await res.json();
  if (data.error) { alert(data.error); return; }
  if (multi && data.paths && data.paths.length) {
    playlistIngest(data.paths);
  } else if (!multi && data.path) {
    handleSelectedPath(prefix, data.path);
  }
}

function handleSelectedPath(prefix, path) {
  if (prefix === 'pm-compare') playlistCompare(path);
  if (prefix === 'qb') qbSelectPath(path);
  if (prefix === 'dl') dlSelectPath(path);
}

// ============================================================
// DRAG & DROP + BROWSER UPLOAD (alternative to native browse)
// ============================================================
function wireDropzone(zoneId, inputId, onPathsReady, multiple) {
  const zone = document.getElementById(zoneId);
  const input = document.getElementById(inputId);
  zone.addEventListener('click', () => input.click());
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', async e => {
    e.preventDefault(); zone.classList.remove('dragover');
    await handleFiles(e.dataTransfer.files, onPathsReady, multiple);
  });
  input.addEventListener('change', async e => {
    await handleFiles(e.target.files, onPathsReady, multiple);
  });
}

async function handleFiles(fileList, onPathsReady, multiple) {
  const files = Array.from(fileList);
  if (!files.length) return;
  const paths = [];
  for (const f of files) {
    const form = new FormData();
    form.append('file', f);
    const res = await fetch('/api/upload', { method: 'POST', body: form });
    const data = await res.json();
    if (data.path) paths.push(data.path);
  }
  onPathsReady(multiple ? paths : paths[0]);
}

wireDropzone('pm-dz-add', 'pm-file-add', (paths) => playlistIngest(Array.isArray(paths) ? paths : [paths]), true);
wireDropzone('pm-dz-compare', 'pm-file-compare', (path) => playlistCompare(path), false);
wireDropzone('qb-dz', 'qb-file', (path) => qbSelectPath(path), false);
wireDropzone('dl-dz', 'dl-file', (path) => dlSelectPath(path), false);

// ============================================================
// DOMAIN 1 — PLAYLIST MANAGER
// ============================================================
async function refreshLibraryStatus() {
  const data = await (await fetch('/api/playlist/status')).json();
  document.getElementById('pm-lib-count').textContent = `${data.count} tracks`;
}

async function refreshSources() {
  const data = await (await fetch('/api/playlist/sources')).json();
  const el = document.getElementById('pm-sources');
  el.innerHTML = data.sources.map(s =>
    `<div>${escHtml(s.filename)} — +${s.added} added, ${s.duplicates} dup, ${s.skipped_no_id} skipped (${s.fed_at})</div>`
  ).join('') || '<div>No files fed yet.</div>';
}

async function playlistIngest(paths) {
  const res = await fetch('/api/playlist/upload', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ paths })
  });
  const data = await res.json();
  const log = document.getElementById('pm-add-log');
  if (data.error) { log.innerHTML = `<div>Error: ${data.error}</div>`; return; }
  log.innerHTML = `<div>+${data.added} added, ${data.duplicates} duplicates, ${data.skipped_no_id} skipped (no track id). Library: ${data.library_size} tracks.</div>`;
  refreshLibraryStatus();
  refreshSources();
}

async function playlistClear() {
  if (!confirm('Clear the entire library? This cannot be undone.')) return;
  await fetch('/api/playlist/clear', { method: 'POST' });
  refreshLibraryStatus();
  refreshSources();
  document.getElementById('pm-add-log').innerHTML = '';
}

async function playlistCompare(path) {
  const res = await fetch('/api/playlist/compare', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path })
  });
  const data = await res.json();
  const el = document.getElementById('pm-compare-result');
  if (data.error) { el.innerHTML = `<div class="log">${data.error}</div>`; return; }
  el.innerHTML = `
    <p class="lead">${data.already_have_count} already have · ${data.to_download_count} to download (of ${data.total_rows})</p>
    ${data.playlist_folder ? `<p class="note">Saved automatically as <code>${escHtml(data.playlist_name)}\\1_to_download.csv</code> in your working folder. <a href="#" onclick="openFolder(${JSON.stringify(data.playlist_folder).replace(/"/g, '&quot;')}); return false;" style="color:var(--accent2)">Open folder</a></p>` : (data.to_download_count === 0 ? '<p class="note">Nothing new to download. You already have every track.</p>' : '')}
    <button class="btn btn-accent" onclick="exportFile(null, '${data.to_download_file}')">Save to_download.csv as…</button>
    <button class="btn" onclick="exportFile(null, '${data.already_have_file}')">Save already_have.csv as…</button>
    <table>
      <thead><tr><th>#</th><th>Title</th><th>Artist</th><th>Length</th><th>Status</th></tr></thead>
      <tbody>${data.table_rows.slice(0, 200).map(r =>
        `<tr><td>${escHtml(r.position)}</td><td>${escHtml(r.title)}</td><td>${escHtml(r.artist)}</td><td>${escHtml(r.length)}</td><td>${escHtml(r.condition)}</td></tr>`
      ).join('')}</tbody>
    </table>`;
}

// ============================================================
// DOMAIN 2 — QOBUZ ENRICH
// ============================================================
let qbSelected = null;
function qbSelectPath(path) {
  qbSelected = path;
  document.getElementById('qb-selected').textContent = path;
  document.getElementById('qb-run-btn').disabled = false;
}

let qbOutput = null;
async function qobuzRun() {
  if (!qbSelected) return;
  $('qb-done-actions').classList.add('hidden');
  const r = await postJSON('/api/qobuz/run', { path: qbSelected });
  if (!r.ok) {
    if (r.data.token_expired) { $('qb-label').textContent = 'Reconnect Qobuz to continue.'; refreshBanner(); }
    else alert(r.data.error || 'Could not start.');
  }
}
async function qobuzStop() { await fetch('/api/qobuz/stop', { method: 'POST' }); }

const qbSource = new EventSource('/api/qobuz/events');
qbSource.onmessage = e => {
  const msg = JSON.parse(e.data);
  if (msg.type === 'ping') return;
  const log = document.getElementById('qb-log');
  if (msg.type === 'started') document.getElementById('qb-label').textContent = `0 / ${msg.total}`;
  if (msg.type === 'track_start') document.getElementById('qb-label').textContent = `${msg.index} — ${msg.title}`;
  if (msg.type === 'track_done') {
    log.innerHTML += `<div>[${msg.index}] ${msg.quality_status} — ${msg.max_bit}bit/${(msg.max_khz/1000).toFixed(1)}kHz</div>`;
    log.scrollTop = log.scrollHeight;
  }
  if (msg.type === 'error') log.innerHTML += `<div>⚠️ ${escHtml(msg.message)}</div>`;
  if (msg.type === 'finished') {
    document.getElementById('qb-progress').style.width = '100%';
    document.getElementById('qb-label').textContent = `Done — ${msg.found} official, ${msg.defaulted} defaulted`;
    qbOutput = msg.output_file;
    loadRecent();
    $('qb-done-actions').classList.remove('hidden');
  }
  if (msg.type === 'token_expired') {
    $('qb-label').textContent = 'Stopped. Qobuz needs to be reconnected.';
    log.innerHTML += `<div>⚠️ ${escHtml(msg.message)}</div>`;
    refreshBanner();
  }
  if (msg.type === 'stopped') document.getElementById('qb-label').textContent = 'Stopped';
};

// ============================================================
// DOMAIN 3 — DOWNLOADER
// ============================================================
let dlSelected = null;
let dlTotal = 0, dlCurrent = 0;
function dlSelectPath(path) {
  dlSelected = path;
  document.getElementById('dl-selected').textContent = path;
  document.getElementById('dl-run-btn').disabled = false;
}

let dlFolder = null;
async function downloaderStart() {
  if (!dlSelected) return;
  document.getElementById('dl-cards').innerHTML = '';
  document.getElementById('dl-folder-actions').classList.add('hidden');
  await fetch('/api/downloader/start', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: dlSelected })
  });
}
async function downloaderStop() { await fetch('/api/downloader/stop', { method: 'POST' }); }

function addCard(id, title, artist, status, badgeText, query) {
  const el = document.createElement('div');
  el.className = `card ${status}`;
  el.id = id;
  el.innerHTML = `
    <div>
      <div class="card-title">${escHtml(title)}</div>
      <div class="card-artist">${escHtml(artist)}</div>
      ${query ? `<div class="card-query">🔍 "${escHtml(query)}"</div>` : ''}
      <div class="card-meta" id="${id}-meta"></div>
    </div>
    <span class="badge ${status}" id="${id}-badge">${badgeText}</span>`;
  document.getElementById('dl-cards').prepend(el);
}
function updateCard(id, status, badgeText, meta) {
  const card = document.getElementById(id);
  if (!card) return;
  card.className = `card ${status}`;
  const badge = document.getElementById(id + '-badge');
  badge.className = `badge ${status}`;
  badge.textContent = badgeText;
  if (meta) {
    document.getElementById(id + '-meta').innerHTML =
      `<span>🎚 ${meta.quality}</span><span>💾 ${meta.size}</span><span>⚡ ${meta.speed}</span><span>👤 ${escHtml(meta.peer)}</span>`;
  }
}
function escHtml(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

const dlSource = new EventSource('/api/downloader/events');
dlSource.onmessage = e => {
  const msg = JSON.parse(e.data);
  if (msg.type === 'ping') return;

  if (msg.type === 'started') { dlTotal = msg.total; document.getElementById('dl-label').textContent = `0 / ${dlTotal} tracks`; }
  if (msg.type === 'card_searching') {
    dlCurrent = msg.index;
    document.getElementById('dl-progress').style.width = Math.round((msg.index - 1) / dlTotal * 100) + '%';
    document.getElementById('dl-label').textContent = `${msg.index} / ${dlTotal} tracks`;
    document.getElementById('dl-stat-progress').textContent = `${msg.index}/${dlTotal}`;
    addCard(msg.id, msg.title, msg.artist, 'searching', 'Searching...', msg.query);
  }
  if (msg.type === 'card_downloading') {
    updateCard(msg.id, 'downloading', `Downloading${msg.attempt > 1 ? ` (try ${msg.attempt}/${msg.max_attempts || 15})` : ''}`,
      { quality: msg.quality, size: msg.size, speed: msg.speed, peer: msg.peer });
  }
  if (msg.type === 'card_retrying') {
    const label = msg.reason === 'slow_peer' ? '🐌 Slow peer, retrying...' : '⚠️ Failed, retrying...';
    updateCard(msg.id, 'retrying', `${label} (${msg.attempt}/${msg.max_attempts})`);
  }
  if (msg.type === 'card_done') {
    updateCard(msg.id, 'done', '✅ Done');
    document.getElementById('dl-progress').style.width = Math.round(dlCurrent / dlTotal * 100) + '%';
  }
  if (msg.type === 'card_failed') updateCard(msg.id, 'failed', '❌ ' + (msg.reason || 'Failed'));
  if (msg.type === 'stats') {
    document.getElementById('dl-stat-done').textContent = msg.done;
    document.getElementById('dl-stat-failed').textContent = msg.failed;
    document.getElementById('dl-stat-skipped').textContent = msg.skipped;
  }
  if (msg.type === 'finished') {
    document.getElementById('dl-progress').style.width = '100%';
    document.getElementById('dl-label').textContent = `Finished — ${msg.done} done, ${msg.failed} failed, ${msg.skipped} skipped`;
    if (msg.playlist_folder) { dlFolder = msg.playlist_folder; document.getElementById('dl-folder-actions').classList.remove('hidden');
      document.getElementById('dl-label').textContent += ` · saved: ${msg.successful_count} downloaded, ${msg.not_downloaded_count} not downloaded`; }
    loadRecent();
    if (msg.slow_skipped && msg.slow_skipped.length) {
      document.getElementById('dl-slow-count').textContent = msg.slow_skipped.length;
      document.getElementById('dl-slow-list').innerHTML = msg.slow_skipped.map(s =>
        `<li><span>${escHtml(s.title)}</span><span>${escHtml(s.artist)}</span></li>`).join('');
      document.getElementById('dl-slow-panel').classList.add('show');
    }
  }
  if (msg.type === 'stopped') document.getElementById('dl-label').textContent = 'Stopped by user';
  if (msg.type === 'error') document.getElementById('dl-label').textContent = '⚠️ ' + msg.message;
};

// ============================================================
// DOMAIN 4 — POST-PROCESSING
// ============================================================
async function postprocessRun() {
  const path = document.getElementById('pp-folder').value.trim();
  if (!path) { alert('Pick a library folder first.'); return; }
  const res = await fetch('/api/postprocess/run', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path })
  });
  const data = await res.json();
  if (data.error) alert(data.error);
}
async function postprocessStop() { await fetch('/api/postprocess/stop', { method: 'POST' }); }

const ppSource = new EventSource('/api/postprocess/events');
ppSource.onmessage = e => {
  const msg = JSON.parse(e.data);
  if (msg.type === 'ping') return;
  const log = document.getElementById('pp-log');
  if (msg.type === 'log') { log.innerHTML += `<div>${escHtml(msg.message)}</div>`; log.scrollTop = log.scrollHeight; }
  if (msg.type === 'started') document.getElementById('pp-label').textContent = `0 / ${msg.albums} albums (+${msg.orphans} orphan tracks)`;
  if (msg.type === 'progress') {
    document.getElementById('pp-progress').style.width = Math.round(msg.done / msg.total * 100) + '%';
    document.getElementById('pp-label').textContent = `${msg.done} / ${msg.total} albums`;
  }
  if (msg.type === 'finished') {
    document.getElementById('pp-progress').style.width = '100%';
    document.getElementById('pp-label').textContent = `Done — ${msg.albums} albums, ${msg.orphans} orphan tracks tagged`;
  }
  if (msg.type === 'stopped') document.getElementById('pp-label').textContent = 'Stopped by user';
  if (msg.type === 'error') document.getElementById('pp-label').textContent = '⚠️ ' + msg.message;
};


// ============================================================
// LIBRARY BACKUP
// ============================================================
async function libraryBackup() {
  const log = $('pm-add-log');
  const r = await postJSON('/api/playlist/backup');
  if (r.data.cancelled) return;
  if (!r.ok) { log.innerHTML = `<div>${escHtml(r.data.error || 'Backup failed.')}</div>`; return; }
  log.innerHTML = `<div>✓ Backup saved (${r.data.count} tracks): ${escHtml(r.data.path)}</div>`;
}

// ============================================================
// FLOATING "LAST FILE" CARD (one per screen, shows what the previous step produced)
// ============================================================
let recentData = {}, recentHidden = {}, recentSig = '';
async function loadRecent() {
  try {
    const d = await (await fetch('/api/recent')).json();
    const sig = JSON.stringify(d);
    if (sig !== recentSig) { recentSig = sig; recentData = d; recentHidden = {}; }
    renderRecent();
  } catch (_) {}
}
function recentCandidate() {
  const d = recentData;
  if (currentView === 'playlist') return d.source ? { title: 'Last playlist file', entry: d.source, hint: 'Tap to compare it again' } : null;
  if (currentView === 'qobuz') return d.to_download ? { title: 'Last to-download list', entry: d.to_download, hint: 'Tap to use it here' } : null;
  if (currentView === 'downloader') return d.enriched ? { title: 'Last enriched list', entry: d.enriched, hint: 'Tap to use it here' } : null;
  if (currentView === 'postprocess') {
    if (d.downloaded) return { title: 'Last downloads landed in', entry: d.downloaded, hint: 'Tap to use this folder' };
    if (d.library_folder) return { title: 'Your music library', entry: { path: d.library_folder, name: '' }, hint: 'Tap to use this folder' };
  }
  return null;
}
function renderRecent() {
  const card = $('recent-card');
  const c = recentCandidate();
  if (!c || recentHidden[currentView]) { card.classList.add('hidden'); return; }
  const base = c.entry.path.split(/[\\/]/).filter(Boolean).pop();
  $('recent-title').textContent = c.title;
  $('recent-name').textContent = (c.entry.name ? c.entry.name + ' · ' : '') + base;
  $('recent-sub').textContent = c.hint + (c.entry.count ? ` · ${c.entry.count} tracks` : '');
  card.classList.remove('hidden', 'added');
}
function hideRecent() { recentHidden[currentView] = true; renderRecent(); }
function useRecent() {
  const c = recentCandidate();
  if (!c) return;
  const p = c.entry.path;
  if (currentView === 'playlist') playlistCompare(p);
  else if (currentView === 'qobuz') qbSelectPath(p);
  else if (currentView === 'downloader') dlSelectPath(p);
  else if (currentView === 'postprocess') $('pp-folder').value = p;
  const card = $('recent-card');
  card.classList.add('added');
  $('recent-sub').textContent = '✓ Added';
}
setInterval(loadRecent, 5000);


// ============================================================
// BACKGROUND MUSIC  (one file = loop, folder = shuffled playlist)
// ============================================================
let bgmUserPaused = false, bgmPath = '', bgmFolder = false, bgmQueue = [], bgmPos = 0, bgmFails = 0, bgmTrackCount = 0;
const bgmEl = () => $('bgm');

// Fisher-Yates; with avoidFirst, the new order never starts with the track that just played.
function bgmShuffle(items, avoidFirst) {
  const a = items.slice();
  for (let i = a.length - 1; i > 0; i--) { const k = Math.floor(Math.random() * (i + 1)); [a[i], a[k]] = [a[k], a[i]]; }
  if (avoidFirst !== undefined && a.length > 1 && a[0].i === avoidFirst) { [a[0], a[a.length - 1]] = [a[a.length - 1], a[0]]; }
  return a;
}
function bgmUi(app) {
  miniRender();
  const path = app.bgm_path || '';
  if (!$('bgm-file')) return;
  const label = path ? path.replace(/[\\/]+$/, '').split(/[\\/]/).pop() : '';
  $('bgm-file').value = path ? label + (bgmFolder && bgmTrackCount ? `  (${bgmTrackCount} tracks, shuffled)` : '') : '';
  $('bgm-enabled').checked = !!app.bgm_enabled && !!path;
  $('bgm-enabled').disabled = !path;
  $('bgm-volume').value = Math.round((typeof app.bgm_volume === 'number' ? app.bgm_volume : 0.4) * 100);
  $('bgm-next').classList.toggle('hidden', !(bgmFolder && bgmTrackCount > 1));
}
function bgmNowPlaying() {
  const el = $('bgm-now'); if (!el) return;
  if (!bgmFolder || !bgmQueue.length) { el.classList.add('hidden'); return; }
  el.classList.remove('hidden');
  el.textContent = `Now playing: ${bgmQueue[bgmPos].name}`;
}
async function bgmLoadSource(app) {
  const audio = bgmEl();
  const d = await (await fetch('/api/bgmusic/tracks')).json();
  bgmFolder = d.kind === 'folder';
  bgmTrackCount = d.tracks.length;
  bgmFails = 0;
  if (!d.tracks.length) { audio.pause(); audio.removeAttribute('src'); bgmFolder = false; bgmQueue = []; bgmUi(app); bgmNowPlaying(); bgmMsg("Couldn't find any music there. Is the file or folder still in place?", true); return; }
  audio.loop = !bgmFolder;
  bgmUserPaused = false;
  if (bgmFolder) { bgmQueue = bgmShuffle(d.tracks); bgmPos = 0; bgmStartTrack(); }
  else { bgmQueue = []; audio.src = '/api/bgmusic?v=' + Date.now(); miniLoadMeta(); }
  bgmUi(app); bgmNowPlaying();
  if (app.bgm_enabled) audio.play().catch(() => bgmWaitForClick());
}
function bgmStartTrack() {
  const audio = bgmEl();
  audio.src = '/api/bgmusic/track/' + bgmQueue[bgmPos].i + '?v=' + Date.now();
  bgmNowPlaying();
  miniLoadMeta();
}
function bgmNext(manual) {
  const audio = bgmEl();
  if (!bgmFolder || !bgmQueue.length) {                 // single file: "next" simply starts it again
    if (manual && audio.getAttribute('src')) { bgmUserPaused = false; audio.currentTime = 0; audio.play().catch(() => bgmWaitForClick()); }
    return;
  }
  bgmPos++;
  if (bgmPos >= bgmQueue.length) {                       // end of the playlist: reshuffle and go again
    const last = bgmQueue[bgmQueue.length - 1].i;
    bgmQueue = bgmShuffle(bgmQueue, last); bgmPos = 0;
  }
  if (manual) bgmUserPaused = false;
  bgmStartTrack();
  if (bgmEnabledNow && !bgmUserPaused) audio.play().catch(() => bgmWaitForClick());
}
function bgmPrev() {
  const audio = bgmEl();
  if (!audio.getAttribute('src')) return;
  bgmUserPaused = false;
  if (!bgmFolder || !bgmQueue.length || audio.currentTime > 3 || bgmPos === 0) { audio.currentTime = 0; }   // like a real player: restart first
  else { bgmPos--; bgmStartTrack(); }
  audio.play().catch(() => bgmWaitForClick());
}
function bgmPlayPause() {                                 // a pause here is temporary: the saved on/off setting is untouched
  const audio = bgmEl();
  if (!audio.getAttribute('src')) return;
  if (audio.paused) { bgmUserPaused = false; audio.play().catch(() => {}); }
  else { bgmUserPaused = true; audio.pause(); }
  miniRender();
}
let bgmEnabledNow = false;
function bgmSync(app) {
  app = app || {};
  const audio = bgmEl();
  const path = app.bgm_path || '', enabled = !!app.bgm_enabled && !!path;
  bgmEnabledNow = enabled;
  audio.volume = Math.min(1, Math.max(0, typeof app.bgm_volume === 'number' ? app.bgm_volume : 0.4));
  if (!path) { audio.pause(); audio.removeAttribute('src'); bgmPath = ''; bgmFolder = false; bgmQueue = []; bgmTrackCount = 0; bgmUi(app); bgmNowPlaying(); return; }
  if (path !== bgmPath) { bgmPath = path; bgmLoadSource(app); return; }   // new choice: (re)load it
  bgmUi(app);
  if (!enabled) { audio.pause(); bgmUserPaused = false; return; }
  if (audio.paused && !bgmUserPaused) audio.play().catch(() => bgmWaitForClick());
}
function bgmWaitForClick() {              // the browser engine may refuse sound until the first click
  const go = () => { if (bgmEnabledNow && !bgmUserPaused) bgmEl().play().catch(() => {}); };
  ['pointerdown', 'keydown'].forEach(ev => window.addEventListener(ev, go, { once: true }));
}
function bgmMsg(text, bad) {
  const el = $('bgm-msg'); if (!el) return;
  el.textContent = text || ''; el.className = 'state-line ' + (bad ? 'bad' : 'none');
}
async function bgmChoose(kind) {
  const b = await postJSON('/api/browse', { mode: kind === 'folder' ? 'folder' : 'file', filetypes: 'audio' });
  if (b.data.error) { bgmMsg(b.data.error, true); return; }
  if (!b.data.path) return;
  const r = await postJSON('/api/bgmusic/set', { path: b.data.path });
  if (!r.ok) { bgmMsg(r.data.error || 'Could not use that.', true); return; }
  bgmMsg('');
  bgmPath = '';                            // force a reload of the new choice
  const cfg = await (await fetch('/api/settings')).json();
  bgmSync(cfg.app);
}
async function bgmRemove() {
  await postJSON('/api/bgmusic/clear');
  bgmMsg('');
  const cfg = await (await fetch('/api/settings')).json();
  bgmSync(cfg.app);
}
async function bgmToggle(on) {
  await postJSON('/api/settings', { app: { bgm_enabled: !!on } });
  const cfg = await (await fetch('/api/settings')).json();
  bgmSync(cfg.app);
}
let bgmVolTimer = null;
function bgmVolume(v, save) {
  const vol = Number(v) / 100;
  bgmEl().volume = vol;
  if (save) { clearTimeout(bgmVolTimer); bgmVolTimer = setTimeout(() => postJSON('/api/settings', { app: { bgm_volume: vol } }), 100); }
}
document.addEventListener('DOMContentLoaded', () => {
  const audio = bgmEl();
  audio.addEventListener('ended', () => { if (bgmFolder) bgmNext(); });          // single files use the loop attribute
  audio.addEventListener('playing', () => { bgmFails = 0; bgmMsg(''); });
  audio.addEventListener('error', () => {
    if (!audio.getAttribute('src')) return;
    if (bgmFolder && bgmQueue.length > 1 && ++bgmFails < bgmQueue.length) { bgmNext(); return; }   // skip an unplayable track
    bgmMsg("Couldn't play that. Is it still there? Try choosing it again.", true);
  });
});

// ============================================================
// RESET / UNINSTALL
// ============================================================
let resetMode = 'reset', resetInfo = null;
const fmtSize = n => n > 1073741824 ? (n / 1073741824).toFixed(1) + ' GB' : n > 1048576 ? (n / 1048576).toFixed(0) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';

async function openReset(mode) {
  resetMode = mode;
  $('reset-msg').textContent = ''; $('reset-msg').className = 'test-result';
  $('reset-title').textContent = mode === 'uninstall' ? 'Uninstall Mucify' : 'Reset Mucify';
  $('reset-lead').textContent = mode === 'uninstall'
    ? 'This removes Mucify and everything it saved on this PC.'
    : 'This clears Mucify back to a fresh install and opens the first-run setup again. The app stays installed.';
  $('reset-go').textContent = mode === 'uninstall' ? 'Uninstall' : 'Reset and restart';
  $('reset-go').disabled = false; $('reset-cancel').disabled = false;
  $('reset-list').innerHTML = '<div class="reset-item">Checking what Mucify saved…</div>';
  $('reset-modal').classList.remove('hidden');
  resetInfo = await (await fetch('/api/reset/preview')).json();
  const i = resetInfo;
  let html = `<div class="reset-item">✓ <b>Settings, Soulseek &amp; Qobuz logins, library index, logs</b> (${fmtSize(i.app_data.size)})<code>${escHtml(i.app_data.path)}</code></div>`;
  if (i.playlists.custom_folder) {
    html += i.playlists.count
      ? `<div class="reset-item"><label><input type="checkbox" id="reset-playlists" checked> <span>Delete the ${i.playlists.count} playlist folder(s) Mucify saved in your working folder<code>${escHtml(i.playlists.path)}</code></span></label></div>`
      : '';
  } else {
    html += `<div class="reset-item"><span class="small" style="margin:0">Your playlist lists (1–4 CSV files) live in the folder above, so they are removed too.</span></div>`;
  }
  if (i.music.exists && i.music.deletable) {
    html += `<div class="reset-item warn"><label><input type="checkbox" id="reset-music"> <span><b style="color:var(--red)">Also delete my music library</b> (${i.music.files} files, ${fmtSize(i.music.size)}). This cannot be undone.<code>${escHtml(i.music.path)}</code></span></label></div>`;
  } else if (i.music.exists) {
    html += `<div class="reset-item"><span class="small" style="margin:0">Your music folder <code style="display:inline">${escHtml(i.music.path)}</code> is not Mucify's default folder, so it is never deleted automatically.</span></div>`;
  }
  if (mode === 'uninstall') {
    html += `<div class="reset-item">${i.can_uninstall ? 'The Windows uninstaller opens next to remove the program itself.'
      : 'This copy wasn\'t installed with the installer (portable version). After the data is cleared, simply delete the Mucify folder.'}</div>`;
  }
  $('reset-list').innerHTML = html;
}
function closeReset() { $('reset-modal').classList.add('hidden'); }
async function confirmReset() {
  const delMusic = !!($('reset-music') && $('reset-music').checked);
  const delPlaylists = !!($('reset-playlists') && $('reset-playlists').checked);
  if (delMusic && !confirm('This permanently deletes the music you downloaded into Mucify\'s library folder. Continue?')) return;
  $('reset-go').disabled = true; $('reset-cancel').disabled = true;
  const r = await postJSON('/api/reset/run', { mode: resetMode, delete_music: delMusic, delete_playlists: delPlaylists });
  const msg = $('reset-msg');
  if (!r.ok) {
    msg.className = 'test-result bad'; msg.textContent = r.data.error || 'Something went wrong.';
    $('reset-go').disabled = false; $('reset-cancel').disabled = false; return;
  }
  msg.className = 'test-result ok';
  msg.textContent = resetMode === 'uninstall' ? 'Cleaning up. Mucify is closing…' : 'Cleaning up. Mucify will reopen in a moment…';
}


// ============================================================
// ABOUT & LEGAL
// ============================================================
async function loadAbout() {
  try {
    const a = await (await fetch('/api/about')).json();
    $('about-version').textContent = a.version;
    $('about-author').textContent = a.author;
    $('about-license').textContent = a.license;
    $('about-link').setAttribute('href', a.url);
    $('about-docs').innerHTML = a.docs.map(d =>
      `<button class="btn btn-ghost" onclick="openLegal('${d.id}')">${escHtml(d.title)}</button>`).join('');
  } catch (_) {}
}
async function openLegal(id) {
  const r = await fetch('/api/legal/' + encodeURIComponent(id));
  const d = await r.json();
  $('legal-title').textContent = d.title || 'Document';
  $('legal-text').textContent = d.text || d.error || '';
  $('legal-text').scrollTop = 0;
  $('legal-modal').classList.remove('hidden');
}
function closeLegal() { $('legal-modal').classList.add('hidden'); }
document.addEventListener('DOMContentLoaded', loadAbout);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeLegal(); });


// ============================================================
// F11 = fullscreen (not remembered between runs)
// ============================================================
document.addEventListener('keydown', e => {
  if (e.key === 'F11') { e.preventDefault(); postJSON('/api/window/fullscreen'); }
});


// ============================================================
// GUIDE page: real folders + About block
// ============================================================
async function loadGuide() {
  try {
    const s = await (await fetch('/api/settings')).json();
    const info = await (await fetch('/api/setup/state')).json();
    $('guide-music').textContent = s.paths.music_vault || info.defaults.music_vault;
    $('guide-work').textContent = s.paths.working_dir || info.defaults.working_dir;
    const work = $('guide-work').textContent;
    $('guide-data').textContent = work.replace(/[\\/]Working[\\/]?$/, '') || '%APPDATA%\\Mucify';
    const a = await (await fetch('/api/about')).json();
    $('guide-author').textContent = a.author;
    $('guide-license').textContent = a.license;
    $('guide-link').setAttribute('href', a.url);
    $('guide-docs').innerHTML = a.docs.map(d =>
      `<button class="btn btn-ghost" onclick="openLegal('${d.id}')">${escHtml(d.title)}</button>`).join('');
  } catch (_) {}
}


// ============================================================
// SIDEBAR MINI PLAYER (follows the background music)
// ============================================================
let miniMeta = null, miniArtUrl = '';
function miniKey() { return bgmFolder && bgmQueue.length ? String(bgmQueue[bgmPos].i) : ''; }
async function miniLoadMeta() {
  const key = miniKey();
  miniMeta = null; miniArtUrl = '';
  miniRender();
  try {
    const r = await fetch(bgmFolder ? '/api/bgmusic/meta/' + key : '/api/bgmusic/meta');
    if (!r.ok) return;
    const m = await r.json();
    if (key !== miniKey()) return;                       // the track changed while we were asking
    miniMeta = m;
    miniArtUrl = m.has_art ? (bgmFolder ? '/api/bgmusic/art/' + key : '/api/bgmusic/art') + '?v=' + Date.now() : '';
  } catch (_) {}
  miniRender();
}
function miniRender() {
  const box = $('mini'); if (!box) return;
  const audio = bgmEl();
  const active = !!bgmPath && bgmEnabledNow && !!audio.getAttribute('src');
  const playing = active && !audio.paused;
  box.classList.toggle('idle', !active);
  box.classList.toggle('playing', playing);
  const img = $('mini-art');
  const wantArt = active && miniArtUrl ? miniArtUrl : '/static/logo.png';
  if (img.dataset.want !== wantArt) {
    img.dataset.want = wantArt;
    img.onerror = () => { img.onerror = null; img.src = '/static/logo.png'; };
    img.src = wantArt;
  }
  let title = "Nothing's playing", artist = '';
  if (active) {
    title = (miniMeta && miniMeta.title) || (bgmFolder && bgmQueue.length ? bgmQueue[bgmPos].name : '') || 'Playing';
    artist = (miniMeta && miniMeta.artist) || '';
  }
  $('mini-title').textContent = title; $('mini-title').title = title;
  $('mini-artist').textContent = artist; $('mini-artist').title = artist;
  $('mini-play').querySelector('use').setAttribute('href', playing ? '#i-pause' : '#i-play');
}
document.addEventListener('DOMContentLoaded', () => {
  const audio = bgmEl();
  ['play', 'pause', 'playing', 'emptied', 'loadstart'].forEach(ev => audio.addEventListener(ev, miniRender));
  miniRender();
});
