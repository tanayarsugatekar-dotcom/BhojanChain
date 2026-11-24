'use strict';
/* BhojanChain web app – vanilla JS, no build step. */

const API = (new URLSearchParams(location.search).get('api') || window.BHOJAN_API || '').replace(/\/$/, '') + '/api';
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
  del(k) { try { localStorage.removeItem(k); } catch { /* ignore */ } },
};

const KIND = {
  MARKET_VENDOR: { label: 'Market vendor', icon: '🧺', donor: true },
  WEDDING_VENUE: { label: 'Wedding venue', icon: '💒', donor: true },
  RESTAURANT: { label: 'Restaurant / dhaba', icon: '🍽️', donor: true },
  NGO: { label: 'NGO / shelter', icon: '🤝', donor: false },
  INDIVIDUAL: { label: 'Person / family in need', icon: '🙏', donor: false },
};
const FRESH_LABEL = { FRESH: '🟢 Fresh', USE_SOON: '🟡 Use soon', URGENT: '🔴 Use now', EXPIRED: '⚫ Expired' };

const S = {
  catalog: null,
  areas: [],
  ride: { from: '', to: '', kg: 20 },
  me: store.get('bc_me', null),
  admin: store.get('bc_admin', null),
  loc: store.get('bc_loc', null),
  tab: 'find',
  f: { radius: 10, group: '', veg: false, free: false, sort: 'auto' },
  net: { kind: '', radius: 15 },
};

/* ------------------------------------------------------------ helpers */
async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (S.me) headers['X-Org-Token'] = S.me.token;
  if (S.admin) headers['X-Admin-Token'] = S.admin;
  let r;
  try { r = await fetch(API + path, { ...opts, headers }); }
  catch { throw new Error('Cannot reach the server. Check your connection.'); }
  if (r.status === 401 && S.me && !path.startsWith('/login')) { // saved session no longer valid
    S.me = null; store.del('bc_me'); updateHeader(); toast('Please log in again', true);
  }
  if (!r.ok) {
    let m = `Request failed (${r.status})`;
    try { const j = await r.json(); if (j.detail) m = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail); } catch { /* keep default */ }
    throw new Error(m);
  }
  return r.json();
}
let toastTimer;
function toast(msg, err = false) {
  const t = $('#toast'); t.textContent = msg; t.className = 'show' + (err ? ' err' : '');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.className = ''; }, 3800);
}
const minsLeft = iso => Math.floor((Date.parse(iso) - Date.now()) / 60000);
function fmtDur(mins) {
  mins = Math.max(0, Math.round(mins));
  if (mins < 60) return `${mins} min`;
  if (mins < 48 * 60) { const h = Math.floor(mins / 60), m = mins % 60; return m ? `${h}h ${m}m` : `${h}h`; }
  return `${Math.round(mins / 1440)} days`;
}
const clock = iso => new Date(iso).toLocaleString([], { hour: 'numeric', minute: '2-digit', ...(minsLeft(iso) > 18 * 60 ? { day: 'numeric', month: 'short' } : {}) });
const phoneLink = p => `tel:${String(p || '').replace(/[^\d+]/g, '')}`;
const num = n => (Math.round(n * 100) / 100).toString();
function freshClass(mins, total) {
  if (mins <= 0) return 'EXPIRED';
  if (mins <= 90) return 'URGENT';
  if (mins <= 360 && (total == null || mins < total * 0.5)) return 'USE_SOON';
  return 'FRESH';
}
const hav = (a, b, c, d) => { const r = Math.PI / 180, dp = (c - a) * r, dl = (d - b) * r;
  const x = Math.sin(dp / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin(dl / 2) ** 2; return 2 * 6371.0088 * Math.asin(Math.sqrt(x)); };
async function loadAreas() { try { S.areas = (await api('/areas')).areas; } catch { S.areas = []; } }
const areaByName = n => S.areas.find(a => a.name === n);
function nearestArea(lat, lng) {
  let best = null, bd = Infinity;
  for (const a of S.areas) { const d = hav(lat, lng, a.lat, a.lng); if (d < bd) { bd = d; best = a; } }
  return best ? { area: best, km: bd } : null;
}

/* ------------------------------------------------------------ ride cost estimate (Rapido / Uber style) */
/* Edit these numbers to match the fares you see in the apps in Belagavi. Fare = base (covers baseKm) + perKm beyond it + booking fee. */
const RIDE = [
  { key: 'rapido_bike', name: 'Rapido Bike', icon: '🏍️', base: 25, baseKm: 2, perKm: 8, fee: 5, maxKg: 15 },
  { key: 'rapido_auto', name: 'Rapido Auto', icon: '🛺', base: 35, baseKm: 2, perKm: 16, fee: 5, maxKg: 100 },
  { key: 'uber_auto', name: 'Uber Auto', icon: '🛺', base: 40, baseKm: 2, perKm: 17, fee: 6, maxKg: 100 },
  { key: 'uber_go', name: 'Uber Go (cab)', icon: '🚕', base: 60, baseKm: 2, perKm: 13, fee: 8, maxKg: 120 },
];
const ROAD_FACTOR = 1.35; // road distance is longer than the straight line
const KG_PER = { kg: 1, litres: 1, plates: 0.4, pieces: 0.08 };
const toKg = (q, u) => q * (KG_PER[u] || 1);
const roadKm = (a, b, c, d) => Math.max(0.5, hav(a, b, c, d) * ROAD_FACTOR);
const round5 = x => Math.max(5, Math.round(x / 5) * 5);
function rideFares(km) {
  return RIDE.map(r => { const f = r.base + Math.max(0, km - r.baseKm) * r.perKm + r.fee; return { ...r, lo: round5(f * 0.9), hi: round5(f * 1.2) }; });
}
function rideHTML(km, kg) {
  const fares = rideFares(km), fit = fares.filter(f => kg <= f.maxKg);
  const best = fit.length ? fit.reduce((a, b) => (a.lo <= b.lo ? a : b)) : null;
  return `<div class="ride"><div class="small"><b>🛵 Pickup ride estimate</b> · ${km.toFixed(1)} km by road · about ${kg < 10 ? kg.toFixed(1) : Math.round(kg)} kg</div>
    <table>${fares.map(f => `<tr class="${best && best.key === f.key ? 'best' : ''}"><td>${f.icon} ${f.name}</td><td>₹${f.lo}–${f.hi}</td><td class="hint">${kg > f.maxKg ? 'too much load' : best && best.key === f.key ? 'cheapest that fits' : 'fits'}</td></tr>`).join('')}</table>
    <p class="hint" style="margin:6px 0 0">Estimate only, from typical Karnataka city fares. Rapido and Uber do not publish rate cards and prices change with time and demand, so check the app for the real fare.${best ? '' : ' This load is too big for one ride; split it or use a pickup van.'}</p></div>`;
}
const myPoint = () => (S.me && S.me.lat != null ? { lat: S.me.lat, lng: S.me.lng } : S.loc);
function rideBlock(lat, lng, kg) {
  const o = myPoint(); if (!o || lat == null) return '';
  return rideHTML(roadKm(o.lat, o.lng, lat, lng), kg);
}

const isDonor = () => S.me && KIND[S.me.kind]?.donor;

const dlg = $('#dlg');
function openDlg(html) { $('#dlgBody').innerHTML = html; if (!dlg.open) dlg.showModal(); return $('#dlgBody'); }
function closeDlg() { if (dlg.open) dlg.close(); }
dlg.addEventListener('click', e => { if (e.target === dlg) closeDlg(); });

function updateHeader() {
  $('#locLabel').textContent = S.loc ? S.loc.label : 'Set location';
  $('#meLabel').textContent = S.me ? `${KIND[S.me.kind].icon} ${S.me.name}` : 'Log in / Sign up';
}

/* ------------------------------------------------------------ freshness widget */
function freshHTML(l) {
  const mins = minsLeft(l.expires_at), cls = freshClass(mins, l.total_shelf_minutes);
  const pct = Math.max(0, Math.min(100, (mins / Math.max(1, l.total_shelf_minutes)) * 100));
  const storage = l.storage === 'COLD' ? '❄️ kept cold' : '🌡️ room temp / hot-held';
  return `<div class="fresh ${cls}" data-exp="${esc(l.expires_at)}" data-total="${l.total_shelf_minutes}">
    <div class="t"><span class="lbl">${FRESH_LABEL[cls]}</span><span class="left">${mins > 0 ? fmtDur(mins) + ' of safe time left' : 'Past safe time'}</span></div>
    <div class="bar"><i style="width:${pct}%"></i></div>
    <div class="hint">Safe to eat until <b>${esc(clock(l.expires_at))}</b> · ${storage}</div></div>`;
}
function tick() {
  $$('.fresh[data-exp]').forEach(el => {
    const mins = minsLeft(el.dataset.exp), total = +el.dataset.total, cls = freshClass(mins, total);
    el.className = `fresh ${cls}`;
    $('.lbl', el).textContent = FRESH_LABEL[cls];
    $('.left', el).textContent = mins > 0 ? fmtDur(mins) + ' of safe time left' : 'Past safe time';
    $('.bar i', el).style.width = Math.max(0, Math.min(100, mins / Math.max(1, total) * 100)) + '%';
    if (mins <= 0) $$('[data-reserve]', el.closest('.card')).forEach(b => { b.disabled = true; b.textContent = 'Expired'; });
  });
}
setInterval(tick, 20000);

/* ------------------------------------------------------------ location */
function setLoc(lat, lng, label, then) {
  S.loc = { lat, lng, label }; store.set('bc_loc', S.loc); updateHeader(); closeDlg();
  if (then) then(); else render();
}
function openLoc(then) {
  const b = openDlg(`<h2>📍 Where are you in Belagavi?</h2>
    <p class="muted small">We show food, NGOs, markets and wedding venues near the area you pick.</p>
    <button class="btn" id="gps" style="width:100%">Use my current location</button>
    <div class="f" style="margin:14px 0 6px"><label for="q">Search your area</label><input id="q" placeholder="e.g. Tilakwadi" autocomplete="off"></div>
    <div class="badges" id="areaList"></div>
    <p class="hint">Area centres are approximate (about 1 km).</p>
    <p style="text-align:right;margin:14px 0 0"><button class="btn ghost sm" id="cancelLoc">Cancel</button></p>`);
  $('#cancelLoc', b).onclick = closeDlg;
  const draw = () => {
    const q = $('#q', b).value.trim().toLowerCase(), list = S.areas.filter(a => [a.name, ...(a.aliases || [])].some(n => n.toLowerCase().includes(q)));
    $('#areaList', b).innerHTML = list.length ? list.map(a => `<button class="btn ghost sm" data-a="${esc(a.name)}">${esc(a.name)}</button>`).join('')
      : `<p class="muted small">${S.areas.length ? 'No Belagavi area matches that.' : 'Could not load the area list. Check your connection and reopen this.'}</p>`;
    $$('[data-a]', b).forEach(btn => btn.onclick = () => { const a = areaByName(btn.dataset.a); setLoc(a.lat, a.lng, a.name, then); });
  };
  $('#q', b).oninput = draw; draw();
  $('#gps', b).onclick = () => {
    if (!navigator.geolocation) return toast('Your browser does not support location', true);
    $('#gps', b).textContent = 'Locating…';
    navigator.geolocation.getCurrentPosition(pos => {
      const { latitude: la, longitude: lo } = pos.coords, n = nearestArea(la, lo);
      if (!n || n.km > 15) { $('#gps', b).textContent = 'Use my current location'; return toast('You seem to be outside Belagavi. Pick an area from the list.', true); }
      setLoc(la, lo, n.area.name, then);
    }, () => { $('#gps', b).textContent = 'Use my current location'; toast('Could not get your location. Pick your area from the list.', true); },
    { enableHighAccuracy: true, timeout: 10000 });
  };
}
function ensureLoc(then) { S.loc ? then() : openLoc(then); }

/* ------------------------------------------------------------ sign up / profile */
function openSignup() {
  (() => {
    let kind = 'NGO';
    const b = openDlg(`<h2>Join BhojanChain</h2>
      <form id="su"><p class="small" style="margin-top:0"><b>Who are you?</b></p>
      <div class="seg" id="kinds">${Object.entries(KIND).map(([k, v]) => `<button type="button" data-k="${k}" class="${k === kind ? 'on' : ''}"><span style="font-size:1.4rem">${v.icon}</span><br><b>${v.label}</b><br><span class="hint">${v.donor ? 'I have surplus food to give' : 'I need food'}</span></button>`).join('')}</div>
      <div class="f" style="margin-top:14px"><label for="n">Name</label><input id="n" required minlength="2" maxlength="80" placeholder="Shop, venue, NGO or your name"></div>
      <div class="f"><label for="p">Mobile number</label><input id="p" required type="tel" minlength="10" maxlength="20" pattern="(?:\\+91[ -]?)?[6-9][0-9]{9}" autocomplete="tel" placeholder="+91 98xxxxxxxx"></div>
      <div class="row"><button type="button" class="btn ghost sm" id="otp">Send OTP</button><div class="f" style="flex:1;margin:0"><label for="suotp">6-digit OTP</label><input id="suotp" type="text" inputmode="numeric" maxlength="6" pattern="[0-9]{6}" placeholder="123456"></div></div>
      <div class="f"><label for="pw">Create a password (6+ characters)</label><input id="pw" required type="password" minlength="6" maxlength="72" autocomplete="new-password"></div>
      <div class="f"><label for="ar">Area of Belagavi</label><select id="ar" required><option value="">Choose your area…</option>${S.areas.map(a => `<option ${S.loc && S.loc.label === a.name ? 'selected' : ''}>${esc(a.name)}</option>`).join('')}</select></div>
      <div class="f"><label for="a" id="aLbl">Address (optional)</label><input id="a" maxlength="120" placeholder="Shop / house no., street, nearest landmark"></div>
      <div class="cols"><div class="f"><label for="pin">Pincode (optional)</label><input id="pin" inputmode="numeric" maxlength="6" pattern="59[01][0-9]{3}" placeholder="590006"></div>
        <div class="f"><label for="pp">Exact map pin (optional)</label><input id="pp" placeholder="15.8497, 74.4977"></div></div>
      <p class="hint">For an exact pin, long-press the spot on Google Maps and paste the coordinates. Otherwise we use the centre of your area. Receivers are matched to donors by this location.</p>
      <p class="hint" id="privacy"></p>
      <div class="row"><button type="button" class="btn ghost" id="cx">Cancel</button><button class="btn">Create profile</button></div>
      <p class="small" style="text-align:center;margin:12px 0 0">Already have an account? <a href="#" id="toLogin">Log in</a></p></form>`);
    $('#toLogin', b).onclick = e => { e.preventDefault(); openLogin(); };
    const refresh = () => {
      $$('#kinds button', b).forEach(x => x.classList.toggle('on', x.dataset.k === kind));
      $('#aLbl', b).textContent = KIND[kind].donor ? 'Pickup address (shown to receivers)' : 'Address (optional)';
      $('#a', b).required = KIND[kind].donor;
      $('#privacy', b).textContent = kind === 'INDIVIDUAL' ? 'Your phone number is only shared with a donor after you reserve food from them.' : '';
    };
    $$('#kinds button', b).forEach(x => x.onclick = () => { kind = x.dataset.k; refresh(); });
    refresh();
    $('#cx', b).onclick = closeDlg;
    $('#otp', b).onclick = async () => {
      const phone = $('#p', b).value.trim();
      if (!phone) return toast('Enter your mobile number first', true);
      $('#otp', b).disabled = true;
      try {
        const r = await api('/otp/request', { method: 'POST', body: JSON.stringify({ phone, purpose: 'signup' }) });
        toast(r.dev_otp ? `Development OTP: ${r.dev_otp}` : 'OTP sent to your mobile number');
        $('#suotp', b).focus();
      } catch (err) { toast(err.message, true); }
      $('#otp', b).disabled = false;
    };
    $('#su', b).onsubmit = async e => {
      e.preventDefault();
      try {
        const area = $('#ar', b).value, raw = $('#pp', b).value.trim(), body = { name: $('#n', b).value, kind, phone: $('#p', b).value, password: $('#pw', b).value, otp: $('#suotp', b).value, area, address: $('#a', b).value, pincode: $('#pin', b).value.trim() || null };
        if (raw) {
          const m = raw.match(/^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$/);
          if (!m) return toast('Map pin must look like 15.8497, 74.4977', true);
          body.lat = +m[1]; body.lng = +m[2];
        }
        const o = await api('/orgs', { method: 'POST', body: JSON.stringify(body) });
        startSession(o, area);
        updateHeader(); closeDlg(); toast(`Welcome, ${o.name}!`); S.tab = KIND[kind].donor ? 'share' : 'find'; syncTabs(); render();
      } catch (err) { toast(err.message, true); }
    };
  })();
}
function startSession(o, area) {
  S.me = { id: o.id, token: o.token, name: o.name, kind: o.kind, phone: o.phone, lat: o.lat, lng: o.lng, area: area || '', address: o.address }; store.set('bc_me', S.me);
  if (!S.loc) { S.loc = { lat: o.lat, lng: o.lng, label: area || (nearestArea(o.lat, o.lng) || { area: { name: 'Belagavi' } }).area.name }; store.set('bc_loc', S.loc); }
}
function openLogin() {
  const b = openDlg(`<h2>Log in</h2>
    <form id="li"><div class="f"><label for="lp">Mobile number</label><input id="lp" required type="tel" pattern="(?:\\+91[ -]?)?[6-9][0-9]{9}" autocomplete="tel" placeholder="+91 98xxxxxxxx"></div>
      <div class="row"><button type="button" class="btn ghost sm" id="logotp">Send OTP</button><div class="f" style="flex:1;margin:0"><label for="lw">Password or 6-digit OTP</label><input id="lw" required autocomplete="one-time-code" placeholder="Password / OTP"></div></div>
      <div class="row"><button type="button" class="btn ghost" id="cx">Cancel</button><button class="btn" id="lgo">Log in</button></div>
      <p class="small" style="text-align:center;margin:12px 0 0">New here? <a href="#" id="toSignup">Create an account</a></p>
      <p class="hint" style="text-align:center">Use an OTP or your existing password. Forgot your password? Contact the BhojanChain admin.</p>
      <p class="small" style="text-align:center"><a href="#" id="toAdmin">Admin login</a></p></form>`);
  $('#cx', b).onclick = closeDlg;
  $('#toSignup', b).onclick = e => { e.preventDefault(); openSignup(); };
  $('#toAdmin', b).onclick = e => { e.preventDefault(); openAdminLogin(); };
  $('#logotp', b).onclick = async () => {
    $('#logotp', b).disabled = true;
    try {
      const r = await api('/otp/request', { method: 'POST', body: JSON.stringify({ phone: $('#lp', b).value, purpose: 'login' }) });
      toast(r.dev_otp ? `Development OTP: ${r.dev_otp}` : 'OTP sent to your mobile number');
      $('#lw', b).focus();
    } catch (err) { toast(err.message, true); }
    $('#logotp', b).disabled = false;
  };
  $('#li', b).onsubmit = async e => {
    e.preventDefault(); $('#lgo', b).disabled = true;
    try {
      const value = $('#lw', b).value;
      const body = /^[0-9]{6}$/.test(value) ? { phone: $('#lp', b).value, otp: value } : { phone: $('#lp', b).value, password: value };
      const o = await api('/login', { method: 'POST', body: JSON.stringify(body) });
      startSession(o); updateHeader(); closeDlg(); toast(`Welcome back, ${o.name}!`); S.tab = KIND[o.kind].donor ? 'activity' : 'find'; syncTabs(); render();
    } catch (err) { toast(err.message, true); $('#lgo', b).disabled = false; }
  };
}
function openProfile() {
  if (!S.me) return openSignup();
  const b = openDlg(`<h2>${KIND[S.me.kind].icon} ${esc(S.me.name)}</h2>
    <p class="muted">${KIND[S.me.kind].label} · ${esc(S.me.phone)}${S.me.address ? '<br>📍 ' + esc(S.me.address) : ''}</p>
    <p class="hint">Your account is saved on the server. Log out here and log in again any time, on any phone, with your mobile number and password.</p>
    ${S.admin ? '<p><button class="btn ghost sm" id="adminPanel">Open admin accounts</button></p>' : ''}
    <div class="row"><button class="btn ghost" id="cx">Close</button><button class="btn danger" id="out">Log out</button></div>`);
  $('#cx', b).onclick = closeDlg;
  if ($('#adminPanel', b)) $('#adminPanel', b).onclick = openAdminPanel;
  $('#out', b).onclick = () => { S.me = null; store.del('bc_me'); updateHeader(); closeDlg(); render(); toast('Logged out'); };
}

function openAdminLogin() {
  const b = openDlg(`<h2>Admin login</h2>
    <form id="al">
      <div class="f"><label for="au">Admin username</label><input id="au" required autocomplete="username"></div>
      <div class="f"><label for="aw">Password</label><input id="aw" required type="password" autocomplete="current-password"></div>
      <div class="row"><button type="button" class="btn ghost" id="cx">Cancel</button><button class="btn">Log in as admin</button></div>
    </form>`);
  $('#cx', b).onclick = closeDlg;
  $('#al', b).onsubmit = async e => {
    e.preventDefault();
    try {
      const r = await api('/admin/login', { method: 'POST', body: JSON.stringify({ username: $('#au', b).value, password: $('#aw', b).value }) });
      S.admin = r.token; store.set('bc_admin', S.admin);
      closeDlg(); await openAdminPanel();
    } catch (err) { toast(err.message, true); }
  };
}

async function openAdminPanel() {
  if (!S.admin) return openAdminLogin();
  try {
    const accounts = await api('/admin/accounts');
    const b = openDlg(`<h2>Admin · Accounts</h2>
      <p class="muted small">${accounts.length} registered account${accounts.length === 1 ? '' : 's'}</p>
      <div style="max-height:55vh;overflow:auto">
        ${accounts.map(a => `<div class="card" style="margin:8px 0"><b>${esc(a.name)}</b> · ${esc(KIND[a.kind]?.label || a.kind)}
          <div class="hint">${esc(a.phone)} · ${esc(a.address || '')}<br>${a.listing_count} listings · ${a.claim_count} claims · ID ${esc(a.id)}</div>
          <button class="btn danger sm" data-delete="${esc(a.id)}" data-name="${esc(a.name)}">Delete account</button></div>`).join('') || '<p class="muted">No accounts.</p>'}
      </div>
      <p style="text-align:right"><button class="btn ghost sm" id="cx">Close</button></p>`);
    $('#cx', b).onclick = closeDlg;
    $$('[data-delete]', b).forEach(btn => btn.onclick = async () => {
      if (!confirm(`Delete ${btn.dataset.name} and their listings and claims?`)) return;
      try {
        await api('/admin/accounts/' + encodeURIComponent(btn.dataset.delete), { method: 'DELETE' });
        toast('Account deleted'); await openAdminPanel();
      } catch (err) { toast(err.message, true); }
    });
  } catch (err) {
    if (err.message.includes('Admin login')) { S.admin = null; store.del('bc_admin'); openAdminLogin(); }
    else toast(err.message, true);
  }
}

/* ------------------------------------------------------------ tabs */
function syncTabs() { $$('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === S.tab)); }
$('#tabs').addEventListener('click', e => { const b = e.target.closest('button[data-tab]'); if (!b) return; S.tab = b.dataset.tab; syncTabs(); render(); });
$('#locBtn').onclick = () => openLoc();
$('#meBtn').onclick = () => (S.me ? openProfile() : openLogin());

let renderSeq = 0;
async function render(silent = false) {
  const seq = ++renderSeq, v = $('#view');
  if (!silent) v.innerHTML = '<p class="empty">Loading…</p>';
  try {
    const html = await ({ find: viewFind, share: viewShare, activity: viewActivity, network: viewNetwork, ride: viewRide, guide: viewGuide }[S.tab])(v);
    if (seq !== renderSeq) return; // a newer render started
    if (silent && v.contains(document.activeElement) && /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName)) { afterHook = null; return; } // never disturb typing
    if (typeof html === 'string') v.innerHTML = html;
    v.querySelectorAll('[data-after]').forEach(() => {});
    afterRender();
  } catch (err) { if (seq === renderSeq && !silent) v.innerHTML = `<p class="empty">⚠️ ${esc(err.message)}</p>`; }
}
let afterHook = null;
function afterRender() { if (afterHook) { const h = afterHook; afterHook = null; h(); } tick(); }

/* ------------------------------------------------------------ FIND FOOD */
function priceHTML(l) {
  if (l.is_free) return `<span class="price free">FREE</span>`;
  return `<span class="price">₹${num(l.price_per_unit)}/${esc(l.unit)}${l.market_price_per_unit ? `<s>₹${num(l.market_price_per_unit)}</s>` : ''}</span>${l.discount_pct ? ` <span class="badge">${l.discount_pct}% off</span>` : ''}`;
}
function listingCard(l, { mine = false } = {}) {
  const k = KIND[l.donor_kind];
  let dist = l.distance_km != null ? `📍 ${l.distance_km.toFixed(1)} km` : '';
  if (l.distance_km != null) { const bk = rideFares(Math.max(0.5, l.distance_km * ROAD_FACTOR))[0]; dist += ` · 🏍️ ride ~₹${bk.lo}–${bk.hi}`; }
  return `<article class="card" data-id="${esc(l.id)}">
    <div class="row" style="align-items:flex-start"><div class="row" style="justify-content:flex-start;align-items:flex-start;gap:10px"><span class="emoji">${l.emoji}</span>
      <div><h3 class="ttl">${esc(l.title)}</h3><div class="muted small">${k.icon} ${esc(l.donor_name)}${dist ? ' · ' + dist : ''}</div></div></div>${priceHTML(l)}</div>
    <div class="badges"><span class="badge ${l.group === 'COOKED' ? 'cooked' : ''}">${l.group === 'COOKED' ? '🍲 Cooked' : '🥬 Raw'}</span>
      <span class="badge ${l.is_veg ? 'veg' : 'nonveg'}">${l.is_veg ? '● Veg' : '● Non-veg'}</span>
      <span class="badge">${num(l.quantity_left)} ${esc(l.unit)} left</span></div>
    ${l.description ? `<div class="small">${esc(l.description)}</div>` : ''}
    ${freshHTML(l)}
    <div class="row wrap"><span class="hint">${esc(l.address || '')}</span>
      ${mine ? '' : `<button class="btn" data-reserve="${esc(l.id)}" ${minsLeft(l.expires_at) <= 0 ? 'disabled' : ''}>${l.is_free ? 'Reserve free' : 'Reserve'}</button>`}</div>
  </article>`;
}
async function viewFind() {
  const f = S.f, p = new URLSearchParams();
  if (S.loc) { p.set('lat', S.loc.lat); p.set('lng', S.loc.lng); p.set('radius_km', f.radius); }
  if (f.group) p.set('group', f.group);
  if (f.veg) p.set('veg_only', '1');
  if (f.free) p.set('free_only', '1');
  p.set('sort', S.loc ? f.sort : 'soonest');
  const list = await api('/listings?' + p);
  afterHook = () => {
    const v = $('#view');
    $$('[data-f]', v).forEach(el => el.onchange = () => {
      const k = el.dataset.f; f[k] = el.type === 'checkbox' ? el.checked : (k === 'radius' ? +el.value : el.value); render();
    });
    const sl = $('#setLoc', v); if (sl) sl.onclick = () => openLoc();
    $$('[data-reserve]', v).forEach(b => b.onclick = () => openReserve(list.find(x => x.id === b.dataset.reserve)));
    const ds = $('#signupNow', v); if (ds) ds.onclick = openSignup;
  };
  const opt = (val, cur, txt) => `<option value="${val}" ${String(val) === String(cur) ? 'selected' : ''}>${txt}</option>`;
  return `${S.loc ? '' : `<div class="banner">📍 <b>Set your location</b> to see food near you, sorted by distance. <button class="btn sm" id="setLoc" style="margin-left:6px">Set location</button></div>`}
    ${S.me ? '' : `<div class="banner info">🙋 Reserving food needs a free profile (NGO or person in need). Have surplus to give? Sign up as a market vendor, wedding venue or restaurant. <button class="btn sm" id="signupNow" style="margin-left:6px">Sign up</button></div>`}
    <div class="filters">
      ${S.loc ? `<select data-f="radius" aria-label="Distance">${[2, 5, 10, 25, 50].map(r => opt(r, f.radius, `Within ${r} km`)).join('')}</select>` : ''}
      <select data-f="group" aria-label="Food type">${opt('', f.group, 'All food')}${opt('COOKED', f.group, '🍲 Cooked')}${opt('RAW', f.group, '🥬 Raw / groceries')}</select>
      ${S.loc ? `<select data-f="sort" aria-label="Sort">${opt('auto', f.sort, 'Nearest first')}${opt('soonest', f.sort, 'Expiring soonest')}</select>` : ''}
      <label class="pill"><input type="checkbox" data-f="veg" ${f.veg ? 'checked' : ''} style="width:auto"> Veg only</label>
      <label class="pill"><input type="checkbox" data-f="free" ${f.free ? 'checked' : ''} style="width:auto"> Free only</label>
    </div>
    <h2>${list.length ? `${list.length} listing${list.length > 1 ? 's' : ''}${S.loc ? ' near ' + esc(S.loc.label) : ''}` : 'Nothing here right now'}</h2>
    ${list.length ? `<div class="grid">${list.map(l => listingCard(l, { mine: S.me && l.org_id === S.me.id })).join('')}</div>`
      : `<div class="empty">No surplus food listed${S.loc ? ` within ${f.radius} km` : ''} with these filters.<br>Try a wider distance, or check back soon – listings appear as markets and wedding venues finish service.</div>`}`;
}

function openReserve(l) {
  if (!S.me) return openSignup();
  const max = l.quantity_left;
  const b = openDlg(`<h2>${l.emoji} ${esc(l.title)}</h2>
    <p class="muted small" style="margin-top:-6px">${esc(l.donor_name)} · ${esc(l.address || '')}</p>
    ${freshHTML(l)}
    <form id="rf" style="margin-top:14px"><div class="f"><label for="qty">How much do you need? (${esc(l.unit)}, max ${num(max)})</label>
      <input id="qty" type="number" min="0.1" max="${max}" step="any" value="${Math.min(max, 1)}" required></div>
      <p class="preview" id="tot"></p><div id="ride"></div>
      <p class="hint">⚠️ Collect it before <b>${esc(clock(l.expires_at))}</b>. Please check smell and appearance before serving, especially for cooked food.</p>
      <div class="row"><button type="button" class="btn ghost" id="cx">Cancel</button><button class="btn" id="go">Reserve</button></div></form>`);
  const upd = () => { const q = +$('#qty', b).value || 0; $('#tot', b).innerHTML = l.is_free ? `<b>Free</b> – ${num(q)} ${esc(l.unit)}` : `Total to pay on pickup: <b>₹${num(q * l.price_per_unit)}</b>`; };
  const rideUpd = () => { $('#ride', b).innerHTML = rideBlock(l.lat, l.lng, toKg(+$('#qty', b).value || 0, l.unit)); };
  $('#qty', b).oninput = () => { upd(); rideUpd(); }; upd(); rideUpd();
  $('#cx', b).onclick = closeDlg;
  $('#rf', b).onsubmit = async e => {
    e.preventDefault(); $('#go', b).disabled = true;
    try {
      const c = await api(`/listings/${l.id}/claims?org_id=${encodeURIComponent(S.me.id)}`, { method: 'POST', body: JSON.stringify({ quantity: +$('#qty', b).value }) });
      showClaim(c, true); render();
    } catch (err) { toast(err.message, true); $('#go', b).disabled = false; }
  };
}
function showClaim(c, fresh = false) {
  const b = openDlg(`<h2>${fresh ? '✅ Reserved!' : 'Reservation'}</h2>
    <p><b>${c.emoji} ${num(c.quantity)} ${esc(c.unit)}</b> of ${esc(c.title)}<br><span class="muted small">${c.total_price ? 'Pay ₹' + num(c.total_price) + ' on pickup' : 'Free'}</span></p>
    <p class="small" style="margin-bottom:4px">Show this pickup code to ${esc(c.donor_name)}:</p><p style="margin-top:0"><span class="code">${esc(c.code)}</span></p>
    <p class="small">📍 ${esc(c.pickup_address || 'Ask the donor for the address')}<br>📞 <a href="${phoneLink(c.donor_phone)}">${esc(c.donor_phone)}</a><br>⏳ Collect within <b>${fmtDur(c.minutes_left)}</b> (safe until ${esc(clock(c.expires_at))})</p>
    ${rideBlock(c.lat, c.lng, toKg(c.quantity, c.unit))}
    <p class="hint">${c.lat ? `<a target="_blank" rel="noopener" href="https://www.openstreetmap.org/?mlat=${c.lat}&mlon=${c.lng}#map=17/${c.lat}/${c.lng}">Open on map ↗</a>` : ''}</p>
    <p style="text-align:right;margin:0"><button class="btn" id="ok">Done</button></p>`);
  $('#ok', b).onclick = closeDlg;
}

/* ------------------------------------------------------------ SHARE FOOD */
async function viewShare() {
  if (!S.catalog) S.catalog = await api('/catalog');
  if (!S.me) { afterHook = () => { $('#su2').onclick = openSignup; }; return `<div class="empty">Sign up as a market vendor, wedding venue or restaurant to share surplus food.<br><br><button class="btn" id="su2">Create donor profile</button></div>`; }
  if (!isDonor()) { afterHook = () => { $('#sw').onclick = () => { S.me = null; store.del('bc_me'); updateHeader(); openSignup(); }; }; return `<div class="empty">Your profile (<b>${KIND[S.me.kind].label}</b>) is for receiving food.<br>Only markets, wedding venues and restaurants can post surplus.<br><br><button class="btn ghost" id="sw">Switch to a donor profile</button></div>`; }

  const items = S.catalog.items, group = g => items.filter(i => i.group === g).map(i => `<option value="${i.key}">${i.emoji} ${esc(i.label)}</option>`).join('');
  afterHook = () => {
    const v = $('#view'), F = $('#sf', v);
    const cur = () => items.find(i => i.key === F.item.value);
    const calc = () => {
      const it = cur(), hrs = F.storage.value === 'COLD' ? it.cold_h : it.room_h, ago = Math.max(0, +F.ago.value || 0);
      const own = F.override.value ? Math.min(hrs, +F.override.value) : hrs, left = (own - ago) * 60;
      const bx = $('#prev', v);
      if (left < 15) { bx.className = 'banner'; bx.innerHTML = `⛔ Only ${fmtDur(Math.max(0, left))} of safe time would remain, too little to share. ${it.note ? esc(it.note) : ''}`; F.go.disabled = true; }
      else {
        const until = new Date(Date.now() + left * 60000).toISOString();
        bx.className = 'preview';
        bx.innerHTML = `⏳ Safe to eat for about <b>${fmtDur(left)}</b> more – until <b>${esc(clock(until))}</b> (${F.storage.value === 'COLD' ? 'cold storage' : 'room temp / hot-held'}).${it.note ? `<br><span class="hint">${esc(it.note)}</span>` : ''}`;
        F.go.disabled = false;
      }
    };
    const onItem = () => { const it = cur(); F.unit.value = it.default_unit; F.veg.checked = it.veg; calc(); };
    F.item.onchange = onItem;
    ['storage', 'ago', 'override'].forEach(n => F[n].oninput = calc);
    F.free.onchange = () => { $('#paid', v).hidden = F.free.checked; };
    onItem();
    F.onsubmit = async e => {
      e.preventDefault(); F.go.disabled = true;
      const free = F.free.checked, body = {
        item_key: F.item.value, title: F.ttl.value || null, description: F.desc.value, quantity: +F.qty.value, unit: F.unit.value,
        price_per_unit: free ? 0 : +F.price.value || 0, market_price_per_unit: free || !F.market.value ? null : +F.market.value,
        storage: F.storage.value, prepared_at: new Date(Date.now() - (+F.ago.value || 0) * 3600000).toISOString(),
        safe_hours_override: F.override.value ? +F.override.value : null, is_veg: F.veg.checked,
      };
      try { await api(`/orgs/${S.me.id}/listings`, { method: 'POST', body: JSON.stringify(body) }); toast('Listed! Nearby NGOs and people can now reserve it.'); S.tab = 'activity'; syncTabs(); render(); }
      catch (err) { toast(err.message, true); F.go.disabled = false; }
    };
  };
  return `<h2>Share surplus food</h2><p class="muted" style="margin-top:-6px">Posting as <b>${esc(S.me.name)}</b>. Pickup is from your registered location.</p>
    <form id="sf" class="card" autocomplete="off">
      <div class="f"><label for="item">What food is it?</label><select id="item" name="item"><optgroup label="🍲 Cooked food">${group('COOKED')}</optgroup><optgroup label="🥬 Raw food &amp; groceries">${group('RAW')}</optgroup></select></div>
      <div class="f"><label for="ttl">Title (optional)</label><input id="ttl" name="ttl" maxlength="80" placeholder="e.g. Veg biryani from tonight's reception"></div>
      <div class="f"><label for="desc">Details (optional)</label><textarea id="desc" name="desc" rows="2" maxlength="300" placeholder="What's in it, how it's packed…"></textarea></div>
      <div class="cols"><div class="f"><label for="qty">Quantity</label><input id="qty" name="qty" type="number" min="0.1" step="any" required value="10"></div>
        <div class="f"><label for="unit">Unit</label><select id="unit" name="unit">${S.catalog.units.map(u => `<option>${u}</option>`).join('')}</select></div></div>
      <div class="f"><label><input type="checkbox" name="free" checked style="width:auto"> Give it away for free</label></div>
      <div class="cols" id="paid" hidden><div class="f"><label for="price">Your price per unit (₹)</label><input id="price" name="price" type="number" min="0" step="any" value="0"></div>
        <div class="f"><label for="market">Normal market price (₹, optional)</label><input id="market" name="market" type="number" min="0" step="any"></div></div>
      <div class="cols"><div class="f"><label for="storage">How is it stored?</label><select id="storage" name="storage"><option value="ROOM">Room temp / kept hot</option><option value="COLD">Refrigerated / cold room</option></select></div>
        <div class="f"><label for="ago">Cooked / bought how many hours ago?</label><input id="ago" name="ago" type="number" min="0" step="0.25" value="0"></div></div>
      <div class="cols"><div class="f"><label for="override">Your own safe-hours limit (optional)</label><input id="override" name="override" type="number" min="0.25" step="0.25" placeholder="only to shorten"></div>
        <div class="f"><label><input type="checkbox" name="veg" style="width:auto"> Vegetarian</label><span class="hint">Auto-set from the food type. Change if needed.</span></div></div>
      <div id="prev" class="preview"></div>
      <button class="btn" name="go" style="width:100%">Publish to nearby NGOs &amp; people</button>
    </form>`;
}

/* ------------------------------------------------------------ MY ACTIVITY */
function claimCard(c, role) {
  const done = c.status !== 'RESERVED';
  const stat = { RESERVED: '🟡 Reserved', PICKED_UP: '✅ Picked up', CANCELLED: '❌ Cancelled' }[c.status];
  const who = role === 'donor'
    ? `For <b>${esc(c.receiver_name)}</b> (${KIND[c.receiver_kind].label}) · <a href="${phoneLink(c.receiver_phone)}">${esc(c.receiver_phone)}</a>`
    : `From <b>${esc(c.donor_name)}</b> · <a href="${phoneLink(c.donor_phone)}">${esc(c.donor_phone)}</a><br>📍 ${esc(c.pickup_address)}`;
  return `<article class="card"><div class="row wrap"><b>${c.emoji} ${num(c.quantity)} ${esc(c.unit)} · ${esc(c.title)}</b><span class="badge">${stat}</span></div>
    <p class="small" style="margin:6px 0">${who}</p>
    <div class="row wrap"><span>Pickup code <span class="code" style="font-size:1.1rem;padding:4px 8px">${esc(c.code)}</span></span>
      <span class="hint">${c.total_price ? '₹' + num(c.total_price) : 'Free'}${!done ? ` · ${c.minutes_left > 0 ? fmtDur(c.minutes_left) + ' left' : 'past safe time'}` : ''}</span></div>
    ${done ? '' : `<div class="row" style="justify-content:flex-end;margin-top:8px">
      ${role === 'donor' ? `<button class="btn sm" data-pick="${c.id}">Mark picked up</button>` : ''}
      <button class="btn danger sm" data-cancel="${c.id}">Cancel</button></div>`}</article>`;
}
async function viewActivity() {
  if (!S.me) { afterHook = () => { $('#su2').onclick = openSignup; }; return `<div class="empty">Sign up or log in to see your reservations and listings.<br><br><button class="btn" id="su2">Sign up</button></div>`; }
  const don = isDonor();
  const [mine, listings, incoming] = await Promise.all([
    api(`/orgs/${S.me.id}/claims`), don ? api(`/orgs/${S.me.id}/listings`) : [], don ? api(`/orgs/${S.me.id}/incoming-claims`) : []]);
  afterHook = () => {
    const v = $('#view');
    $$('[data-pick]', v).forEach(b => b.onclick = async () => { try { await api(`/orgs/${S.me.id}/claims/${b.dataset.pick}/pickup`, { method: 'POST' }); toast('Marked as picked up'); render(); } catch (e) { toast(e.message, true); } });
    $$('[data-cancel]', v).forEach(b => b.onclick = async () => { if (!confirm('Cancel this reservation? The food goes back on the list.')) return; try { await api(`/orgs/${S.me.id}/claims/${b.dataset.cancel}/cancel`, { method: 'POST' }); toast('Reservation cancelled'); render(); } catch (e) { toast(e.message, true); } });
    $$('[data-close]', v).forEach(b => b.onclick = async () => { if (!confirm('Take this listing down?')) return; try { await api(`/orgs/${S.me.id}/listings/${b.dataset.close}/close`, { method: 'POST' }); toast('Listing removed'); render(); } catch (e) { toast(e.message, true); } });
  };
  const sec = (t, body, empty) => `<h2>${t}</h2>${body || `<p class="muted">${empty}</p>`}`;
  return `${don ? sec(`Reservations on my food (${incoming.length})`, incoming.map(c => claimCard(c, 'donor')).join(''), 'Nobody has reserved your food yet.')
    + sec(`My listings (${listings.length})`, listings.length ? `<div class="grid">${listings.map(l => `<div>${listingCard(l, { mine: true })}${l.status === 'ACTIVE' ? `<p style="text-align:right;margin:6px 0 14px"><button class="btn danger sm" data-close="${l.id}">Take down</button></p>` : '<p class="hint">Closed</p>'}</div>`).join('')}</div>` : '', 'You have not shared anything yet. Use the Share food tab.') : ''}
    ${sec(`My reservations (${mine.length})`, mine.map(c => claimCard(c, 'receiver')).join(''), 'You have not reserved any food yet. Find some in the Find food tab.')}`;
}

/* ------------------------------------------------------------ NEARBY NETWORK */
async function viewNetwork() {
  if (!S.loc) { afterHook = () => { $('#sl').onclick = () => openLoc(); }; return `<div class="empty">Set your location to see NGOs, markets, wedding venues and restaurants around you.<br><br><button class="btn" id="sl">Set location</button></div>`; }
  const n = S.net, p = new URLSearchParams({ lat: S.loc.lat, lng: S.loc.lng, radius_km: n.radius });
  if (n.kind) p.set('kind', n.kind);
  const orgs = await api('/orgs/nearby?' + p);
  afterHook = () => { $$('[data-n]', $('#view')).forEach(el => el.onchange = () => { n[el.dataset.n] = el.dataset.n === 'radius' ? +el.value : el.value; render(); }); };
  const opt = (v, cur, t) => `<option value="${v}" ${String(v) === String(cur) ? 'selected' : ''}>${t}</option>`;
  return `<h2>Nearby network</h2><p class="muted" style="margin-top:-6px">Organisations registered near <b>${esc(S.loc.label)}</b>. Call them directly to coordinate.</p>
    <div class="filters"><select data-n="kind" aria-label="Type">${opt('', n.kind, 'Everyone')}${['NGO', 'MARKET_VENDOR', 'WEDDING_VENUE', 'RESTAURANT'].map(k => opt(k, n.kind, `${KIND[k].icon} ${KIND[k].label}`)).join('')}</select>
      <select data-n="radius" aria-label="Distance">${[5, 15, 30, 60].map(r => opt(r, n.radius, `Within ${r} km`)).join('')}</select></div>
    ${orgs.length ? `<div class="grid">${orgs.map(o => `<article class="card"><div class="row"><b>${KIND[o.kind].icon} ${esc(o.name)}</b><span class="badge">${o.distance_km.toFixed(1)} km</span></div>
      <div class="muted small">${KIND[o.kind].label}${o.address ? ' · ' + esc(o.address) : ''}</div>
      <div class="row"><a class="btn ghost sm" href="${phoneLink(o.phone)}">📞 ${esc(o.phone)}</a><a class="small" target="_blank" rel="noopener" href="https://www.openstreetmap.org/?mlat=${o.lat}&mlon=${o.lng}#map=16/${o.lat}/${o.lng}">Map ↗</a></div></article>`).join('')}</div>`
      : '<div class="empty">No registered organisations in this area yet. Be the first to sign up and invite your local market or NGO.</div>'}`;
}

/* ------------------------------------------------------------ RIDE COST */
async function viewRide() {
  const r = S.ride, names = S.areas.map(a => a.name);
  if (!r.from) { r.from = (S.loc && names.includes(S.loc.label) ? S.loc.label : names[0]) || ''; }
  if (!r.to) r.to = names.find(n => n !== r.from) || r.from;
  const opt = (cur, n) => `<option ${n === cur ? 'selected' : ''}>${esc(n)}</option>`;
  afterHook = () => {
    const v = $('#view'), draw = () => {
      const a = areaByName($('#rf', v).value), b = areaByName($('#rt', v).value), kg = Math.max(0.1, +$('#rkg', v).value || 0.1);
      r.from = a.name; r.to = b.name; r.kg = kg;
      $('#rout', v).innerHTML = rideHTML(roadKm(a.lat, a.lng, b.lat, b.lng), kg);
    };
    ['rf', 'rt', 'rkg'].forEach(id => { $('#' + id, v).oninput = draw; }); draw();
  };
  if (!names.length) return '<div class="empty">Could not load the Belagavi area list. Check your connection and reopen this tab.</div>';
  return `<h2>Ride cost</h2><p class="muted" style="margin-top:-6px">Estimate what a Rapido or Uber ride costs to move food between two parts of Belagavi.</p>
    <div class="card"><div class="cols"><div class="f"><label for="rf">Pickup from</label><select id="rf">${names.map(n => opt(r.from, n)).join('')}</select></div>
      <div class="f"><label for="rt">Deliver to</label><select id="rt">${names.map(n => opt(r.to, n)).join('')}</select></div></div>
      <div class="f"><label for="rkg">Load (kg). 1 plate is about 0.4 kg</label><input id="rkg" type="number" min="0.1" step="any" value="${r.kg}"></div></div>
    <div id="rout"></div>`;
}

/* ------------------------------------------------------------ SHELF-LIFE GUIDE */
async function viewGuide() {
  if (!S.catalog) S.catalog = await api('/catalog');
  const row = i => `<tr><td>${i.emoji} ${esc(i.label)}${i.veg ? '' : ' <span class="badge nonveg">Non-veg</span>'}</td><td>${fmtDur(i.room_h * 60)}</td><td>${fmtDur(i.cold_h * 60)}</td><td class="small muted">${esc(i.note)}</td></tr>`;
  const tbl = (g, t) => `<h2>${t}</h2><div class="card tablewrap"><table><thead><tr><th>Food</th><th>Room temp / hot</th><th>Fridge / cold</th><th>Note</th></tr></thead><tbody>${S.catalog.items.filter(i => i.group === g).map(row).join('')}</tbody></table></div>`;
  return `<div class="banner info"><b>How long does it stay good?</b> BhojanChain counts from when the food was cooked (or bought) and uses conservative food-safety limits. Every listing shows a live countdown and the time it is safe until. Donors can shorten the limit but never extend it, and expired food disappears automatically.</div>
    ${tbl('COOKED', '🍲 Cooked food')}${tbl('RAW', '🥬 Raw food &amp; groceries')}
    <p class="hint">These are guidelines, not guarantees. Hot weather, open containers and long transport shorten safe time. Always check smell, colour and texture, and reheat cooked food until steaming hot. When in doubt, throw it out.</p>`;
}

/* ------------------------------------------------------------ boot */
loadAreas().then(() => { updateHeader(); syncTabs(); render(); });

/* ------------------------------------------------------------ live updates */
/* Every 15 seconds (and when the app comes back to the screen) re-read the lists so food listed or reserved on any other phone appears without a refresh. */
const LIVE_TABS = ['find', 'activity', 'network'];
function liveRefresh() { if (!document.hidden && !dlg.open && LIVE_TABS.includes(S.tab)) render(true); }
setInterval(liveRefresh, 15000);
document.addEventListener('visibilitychange', liveRefresh);
window.addEventListener('online', liveRefresh);
