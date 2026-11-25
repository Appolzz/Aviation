/**
 * LootRadar — app.js
 * Client-side logic: data loading, filtering, sorting, rendering, modal, photo-on-demand
 */

'use strict';

// ============================================================
// Constants
// ============================================================
const RARITY_ORDER = ['Mythic', 'Legendary', 'Epic', 'Rare', 'Uncommon', 'Common'];

const RARITY_CLASS = {
  Mythic:    'mythic',
  Legendary: 'legendary',
  Epic:      'epic',
  Rare:      'rare',
  Uncommon:  'uncommon',
  Common:    'common',
};

const RARITY_COLOR = {
  Common:    '#64748b',
  Uncommon:  '#22c55e',
  Rare:      '#3b82f6',
  Epic:      '#a855f7',
  Legendary: '#f59e0b',
  Mythic:    '#ef4444',
};

const RARITY_GLOW = {
  Common:    'rgba(100,116,139,0.2)',
  Uncommon:  'rgba(34,197,94,0.3)',
  Rare:      'rgba(59,130,246,0.3)',
  Epic:      'rgba(168,85,247,0.35)',
  Legendary: 'rgba(245,158,11,0.35)',
  Mythic:    'rgba(239,68,68,0.4)',
};

const RARITY_EMOJI = {
  Mythic: '👑', Legendary: '🌟', Epic: '✨', Rare: '💙', Uncommon: '🟢', Common: '⬜',
};

// SVG silhouettes keyed by rough category
const SILHOUETTES = {
  widebody: `<svg viewBox="0 0 200 80" fill="none" xmlns="http://www.w3.org/2000/svg" width="120" height="48">
    <path d="M10 42 Q40 36 70 36 L80 24 L90 24 L85 36 L140 34 Q160 34 170 38 L185 38 L185 42 L170 42 L140 42 L85 44 L90 56 L80 56 L70 44 L10 44 Z" fill="currentColor"/>
    <path d="M60 36 L60 20 L120 20 L115 36" fill="currentColor" opacity="0.7"/>
    <path d="M140 42 L155 50 L165 50 L150 42" fill="currentColor" opacity="0.7"/>
  </svg>`,
  narrowbody: `<svg viewBox="0 0 200 72" fill="none" xmlns="http://www.w3.org/2000/svg" width="120" height="48">
    <path d="M12 38 Q40 33 68 33 L78 20 L86 20 L82 33 L150 31 Q168 31 178 36 L190 36 L190 40 L178 40 L150 40 L82 42 L86 52 L78 52 L68 40 L12 42 Z" fill="currentColor"/>
    <path d="M62 33 L62 16 L110 16 L106 33" fill="currentColor" opacity="0.7"/>
    <path d="M148 40 L160 48 L170 48 L156 40" fill="currentColor" opacity="0.6"/>
  </svg>`,
  regional: `<svg viewBox="0 0 180 64" fill="none" xmlns="http://www.w3.org/2000/svg" width="110" height="44">
    <path d="M14 34 Q38 29 60 29 L70 18 L78 18 L74 29 L130 28 Q148 28 158 32 L166 32 L166 36 L158 36 L130 36 L74 38 L78 46 L70 46 L60 36 L14 36 Z" fill="currentColor"/>
    <path d="M56 29 L56 14 L96 14 L93 29" fill="currentColor" opacity="0.7"/>
    <path d="M128 36 L140 44 L148 44 L136 36" fill="currentColor" opacity="0.6"/>
  </svg>`,
  quadjet: `<svg viewBox="0 0 220 88" fill="none" xmlns="http://www.w3.org/2000/svg" width="130" height="52">
    <path d="M10 46 Q44 38 76 38 L88 22 L98 22 L92 38 L155 36 Q178 36 190 42 L205 42 L205 46 L190 46 L155 46 L92 48 L98 62 L88 62 L76 46 L10 48 Z" fill="currentColor"/>
    <path d="M68 38 L68 18 L136 18 L131 38" fill="currentColor" opacity="0.7"/>
    <path d="M56 38 L56 24 L68 24 L68 38" fill="currentColor" opacity="0.5"/>
    <path d="M131 38 L136 24 L148 24 L148 38" fill="currentColor" opacity="0.5"/>
    <path d="M152 46 L168 56 L180 56 L162 46" fill="currentColor" opacity="0.7"/>
    <path d="M162 46 L172 56 L184 56 L174 46" fill="currentColor" opacity="0.5"/>
  </svg>`,
  military: `<svg viewBox="0 0 200 80" fill="none" xmlns="http://www.w3.org/2000/svg" width="120" height="48">
    <path d="M20 44 L60 32 L70 18 L85 18 L78 32 L150 30 Q172 28 185 38 L190 44 L185 50 L150 50 L78 48 L85 62 L70 62 L60 48 L20 46 Z" fill="currentColor"/>
    <path d="M60 32 L44 20 L52 18 L65 32" fill="currentColor" opacity="0.6"/>
    <path d="M150 50 L162 60 L172 58 L158 46" fill="currentColor" opacity="0.7"/>
  </svg>`,
};

// ============================================================
// State
// ============================================================
let state = {
  flights: [],
  meta: {},
  airports: [],
  presets: [],
  activeRarity: 'all',
  activeAirport: 'all',
  activeTime: 'all',
  hideCommon: false,
  searchQuery: '',
};

// ============================================================
// Utils
// ============================================================

/**
 * Parse a local ISO time string to hours and minutes.
 * Returns null if unparseable.
 */
function parseLocalTime(isoStr) {
  if (!isoStr) return null;
  // Accepts "2026-11-25T14:30:00-05:00" or similar
  const timePart = isoStr.slice(11, 16); // "14:30"
  if (!timePart || !timePart.includes(':')) return null;
  const [h, m] = timePart.split(':').map(Number);
  if (isNaN(h) || isNaN(m)) return null;
  return { h, m };
}

/**
 * Format local arrival time for display.
 * Returns "14:30" (24h) string.
 */
function formatArrivalTime(flight) {
  const local = flight.arrival.revised_local || flight.arrival.scheduled_local;
  const t = parseLocalTime(local);
  if (!t) return '--:--';
  return `${String(t.h).padStart(2, '0')}:${String(t.m).padStart(2, '0')}`;
}

/**
 * Detect time-of-day from local time string.
 */
function getTimeOfDay(local) {
  const t = parseLocalTime(local);
  if (!t) return 'unknown';
  if (t.h >= 5 && t.h < 12) return 'morning';
  if (t.h >= 12 && t.h < 17) return 'afternoon';
  if (t.h >= 17 && t.h < 21) return 'evening';
  return 'night';
}

/**
 * Format a UTC ISO timestamp into a friendly "last updated" string.
 */
function formatLastUpdated(isoStr) {
  if (!isoStr) return 'Never';
  try {
    const dt = new Date(isoStr);
    return dt.toLocaleString('en-US', {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
      timeZoneName: 'short',
    });
  } catch { return isoStr; }
}

/**
 * Format a date string (YYYY-MM-DD) into a readable banner.
 */
function formatTargetDate(dateStr) {
  if (!dateStr) return '';
  try {
    // Parse as local date to avoid UTC offset issues
    const [y, mo, d] = dateStr.split('-').map(Number);
    const dt = new Date(y, mo - 1, d);
    return dt.toLocaleDateString('en-US', {
      weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
    });
  } catch { return dateStr; }
}

/**
 * Escape HTML entities.
 */
function esc(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * Show a toast message.
 */
function showToast(msg, duration = 2500) {
  const toast = document.getElementById('toast');
  toast.textContent = msg;
  toast.classList.add('show');
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => toast.classList.remove('show'), duration);
}

/**
 * Copy text to clipboard and show toast.
 */
async function copyToClipboard(text, label = 'Copied!') {
  try {
    await navigator.clipboard.writeText(text);
    showToast(`📋 ${label}`);
  } catch {
    showToast('⚠️ Copy failed — try manually');
  }
}

// ============================================================
// Silhouette helper
// ============================================================
function getSilhouetteSVG(flight) {
  const type = (flight.aircraft.icao_type || '').toUpperCase();
  const cat = (flight.plane_alert_category || '').toLowerCase();

  if (cat.includes('military') || ['C17','C130','C5M','T38','F16','F15','F22','F35','B52','KC135','KC46','VC25','C40','C32','C37'].includes(type)) {
    return SILHOUETTES.military;
  }
  if (['B748','B744','A388','A346','A343','MD11','DC10','AN124'].includes(type)) {
    return SILHOUETTES.quadjet;
  }
  if (['B763','B764','B772','B77W','B77L','B788','B789','B78X','A332','A333','A339','A359','A35K'].includes(type)) {
    return SILHOUETTES.widebody;
  }
  if (['CRJ2','CRJ7','CRJ9','E145','E170','E175','E75L','E75S','AT72','AT76','DH8D'].includes(type)) {
    return SILHOUETTES.regional;
  }
  return SILHOUETTES.narrowbody;
}

// ============================================================
// Filtering
// ============================================================
function applyFilters(flights) {
  const { activeRarity, activeAirport, activeTime, hideCommon, searchQuery } = state;
  const q = searchQuery.trim().toLowerCase();

  return flights.filter(f => {
    // Rarity
    if (activeRarity !== 'all' && f.rarity !== activeRarity) return false;

    // Hide common
    if (hideCommon && f.rarity === 'Common') return false;

    // Airport
    if (activeAirport !== 'all' && f.airport !== activeAirport) return false;

    // Time of day
    if (activeTime !== 'all') {
      const local = f.arrival.revised_local || f.arrival.scheduled_local;
      if (getTimeOfDay(local) !== activeTime) return false;
    }

    // Search
    if (q) {
      const haystack = [
        f.flight_number,
        f.airline.name, f.airline.iata, f.airline.icao,
        f.origin.iata, f.origin.icao, f.origin.name,
        f.aircraft.reg, f.aircraft.modeS, f.aircraft.model, f.aircraft.icao_type,
        f.rarity_reason, f.livery_or_note,
        f.airport,
        ...(f.plane_alert_tags || []),
      ].filter(Boolean).map(s => s.toLowerCase()).join(' ');
      if (!haystack.includes(q)) return false;
    }

    return true;
  });
}

// ============================================================
// Rendering
// ============================================================

function renderAirportPills(airports) {
  const container = document.getElementById('airport-pills');
  container.innerHTML = airports.map(a => `
    <div class="airport-pill">${esc(a)}</div>
  `).join('');
}

function renderDateBanner(meta) {
  const el = document.getElementById('date-banner');
  if (meta.is_sample_data) {
    el.innerHTML = `<strong>Sample Data</strong> — Run the GitHub Action to get live arrivals`;
    return;
  }
  const dateStr = formatTargetDate(meta.target_date);
  el.innerHTML = `Tomorrow's Arrivals: <strong>${dateStr}</strong>`;
}

function renderLastUpdated(meta) {
  const el = document.getElementById('last-updated');
  const ts = formatLastUpdated(meta.last_updated_utc);
  el.innerHTML = `<span class="update-dot"></span>Updated ${ts}`;
}

function renderAirportFilterTabs(airports) {
  const container = document.getElementById('airport-filter-group');
  const tabs = [{ label: 'All Airports', value: 'all' }, ...airports.map(a => ({ label: a, value: a }))];
  container.innerHTML = tabs.map(t => `
    <button class="filter-tab${state.activeAirport === t.value ? ' active' : ''}"
            data-airport="${esc(t.value)}">${esc(t.label)}</button>
  `).join('');
  container.querySelectorAll('.filter-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      state.activeAirport = btn.dataset.airport;
      renderAll();
    });
  });
}

function updateRarityCounts(flights) {
  const counts = { all: flights.length };
  RARITY_ORDER.forEach(r => {
    counts[r] = flights.filter(f => f.rarity === r).length;
  });
  document.getElementById('count-all').textContent = counts.all;
  RARITY_ORDER.forEach(r => {
    const el = document.getElementById(`count-${r.toLowerCase()}`);
    if (el) el.textContent = counts[r];
  });
}

function buildCardHTML(flight) {
  const rClass = RARITY_CLASS[flight.rarity] || 'common';
  const color = RARITY_COLOR[flight.rarity] || '#64748b';
  const glow = RARITY_GLOW[flight.rarity] || 'transparent';
  const time = formatArrivalTime(flight);
  const statusClass = (flight.status || 'scheduled').toLowerCase();
  const hasPhoto = flight.photo && (flight.photo.url || flight.photo.thumbnail);

  // Terminal / gate display
  const termGate = [
    flight.arrival.terminal ? `T${flight.arrival.terminal}` : null,
    flight.arrival.gate ? `G${flight.arrival.gate}` : null,
  ].filter(Boolean).join(' · ');

  // Photo or silhouette
  let photoHTML;
  if (hasPhoto) {
    const imgSrc = esc(flight.photo.url || flight.photo.thumbnail);
    const creditName = esc(flight.photo.photographer || 'Planespotters.net');
    const creditLink = esc(flight.photo.link || 'https://www.planespotters.net');
    photoHTML = `
      <img src="${imgSrc}" alt="Photo of ${esc(flight.aircraft.reg || flight.aircraft.model)}"
           loading="lazy" onerror="this.parentElement.innerHTML=buildSilhouette('${esc(flight.id)}')">
      <div class="card-photo-credit">
        <a href="${creditLink}" target="_blank" rel="noopener">📷 ${creditName}</a>
      </div>
    `;
  } else {
    const silSVG = getSilhouetteSVG(flight);
    const hasReg = !!(flight.aircraft.reg || flight.aircraft.modeS);
    photoHTML = `
      <div class="card-silhouette" style="color: ${color}">
        ${silSVG}
        ${hasReg ? `<button class="btn-load-photo" onclick="loadPhotoForCard('${esc(flight.id)}', this)">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/>
          </svg>
          Load Photo
        </button>` : ''}
      </div>
    `;
  }

  // Rarity reason or livery note
  const reasonLabel = flight.livery_or_note || flight.rarity_reason || flight.rarity;
  const liveryCls = flight.plane_alert_match ? ` style="border-color: ${color}44; color: ${color}"` : '';

  // Origin display
  const originDisplay = flight.origin.iata
    ? `${esc(flight.origin.iata)} (${esc(flight.origin.name || flight.origin.iata)})`
    : (esc(flight.origin.name) || '???');

  // Aircraft display
  const icaoType = flight.aircraft.icao_type || '';
  const model = flight.aircraft.model || 'Unknown Type';
  const reg = flight.aircraft.reg || '';

  return `
    <div class="flight-card rarity-${rClass}"
         id="card-${esc(flight.id)}"
         data-id="${esc(flight.id)}"
         style="--card-color: ${color}; --card-glow: ${glow}">

      <!-- Photo / Silhouette -->
      <div class="card-photo" id="photo-${esc(flight.id)}">
        ${photoHTML}
      </div>

      <div class="card-body">

        <!-- Rarity badge + livery pill -->
        <div class="card-rarity-row">
          <span class="rarity-badge ${rClass}">
            ${RARITY_EMOJI[flight.rarity] || ''} ${esc(flight.rarity)}
          </span>
          ${reasonLabel ? `<span class="livery-pill" title="${esc(reasonLabel)}"${liveryCls}>${esc(reasonLabel)}</span>` : ''}
        </div>

        <!-- Airport + time + status -->
        <div class="card-meta-row">
          <span class="airport-badge">${esc(flight.airport)}</span>
          <span class="arrival-time">${time}<span class="time-tz">local</span></span>
          <span class="status-badge ${statusClass}">${esc(flight.status || 'Scheduled')}</span>
        </div>

        <!-- Flight number + airline -->
        <div class="card-flight-row">
          <span class="flight-num">${esc(flight.flight_number || '???')}</span>
          <span class="airline-name">• ${esc(flight.airline.name || 'Unknown Airline')}</span>
        </div>

        <!-- Route -->
        <div class="card-route">
          <span class="route-origin" title="${esc(flight.origin.name)}">${esc(flight.origin.iata || '???')}</span>
          <span class="route-arrow">✈</span>
          <span class="route-dest">${esc(flight.airport)}</span>
          <span class="route-terminal">${esc(termGate)}</span>
        </div>

        <!-- Aircraft details -->
        <div class="card-aircraft">
          <span class="aircraft-model" title="${esc(model)}">${esc(model)}</span>
          ${icaoType ? `<span class="aircraft-type">${esc(icaoType)}</span>` : ''}
          ${reg ? `<span class="aircraft-reg">${esc(reg)}</span>` : ''}
        </div>

        <!-- Track button -->
        <a class="btn-fr24"
           href="${esc(flight.fr24_url)}"
           target="_blank" rel="noopener"
           aria-label="Track ${esc(flight.flight_number)} on Flightradar24">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M17.8 19.2L16 11l3.5-3.5C21 6 21 4 19.5 2.5S18 2 16.5 3.5L13 7 4.8 5.2C4.3 5.1 3.9 5.4 3.8 5.8l-.4 1.5c-.1.5.2 1 .6 1.2L10 11l-3.3 4L4 16l-1 2 2-1 1.3-2.7L10 11l2.5 6c.2.4.7.7 1.2.6l1.5-.4c.4-.1.7-.5.6-1z"/>
          </svg>
          Track on Flightradar24
        </a>

      </div>
    </div>
  `;
}

function renderFlightGrid(flights) {
  const grid = document.getElementById('flights-grid');
  const empty = document.getElementById('empty-state');
  const countEl = document.getElementById('result-count-num');

  countEl.textContent = flights.length;

  if (flights.length === 0) {
    grid.hidden = true;
    empty.hidden = false;
    return;
  }

  empty.hidden = true;
  grid.hidden = false;
  grid.innerHTML = flights.map(f => buildCardHTML(f)).join('');
}

function renderModal(airports, presets) {
  // Current airports
  const currentEl = document.getElementById('modal-current-airports');
  currentEl.innerHTML = airports.map(a => `
    <div class="modal-airport-pill">✈ ${esc(a)}</div>
  `).join('');

  // Presets
  const presetGrid = document.getElementById('preset-grid');
  presetGrid.innerHTML = presets.map(p => {
    const json = JSON.stringify({ active: p.airports }, null, 2);
    return `
      <div class="preset-card"
           onclick="copyPreset(${JSON.stringify(json)}, ${JSON.stringify(p.name)})"
           role="button" tabindex="0"
           onkeydown="if(event.key==='Enter')this.click()">
        <span class="preset-name">✈ ${esc(p.name)}</span>
        <span class="preset-desc">${esc(p.description)}</span>
        <span class="preset-copy-hint">Click to copy JSON</span>
      </div>
    `;
  }).join('');
}

function renderAll() {
  const filtered = applyFilters(state.flights);
  updateRarityCounts(state.flights); // always show totals for unfiltered
  renderAirportFilterTabs(state.airports);
  updateActiveRarityPills();
  updateActiveTimeTabs();
  updateHideCommonBtn();
  renderFlightGrid(filtered);
}

function updateActiveRarityPills() {
  document.querySelectorAll('.rarity-pill').forEach(el => {
    el.classList.toggle('active', el.dataset.rarity === state.activeRarity);
  });
}

function updateActiveTimeTabs() {
  document.querySelectorAll('[data-time]').forEach(el => {
    el.classList.toggle('active', el.dataset.time === state.activeTime);
  });
}

function updateHideCommonBtn() {
  const btn = document.getElementById('btn-toggle-common');
  btn.classList.toggle('active', state.hideCommon);
  btn.innerHTML = state.hideCommon
    ? `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
         <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>
       </svg>
       Show Common`
    : `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
         <path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94"/>
         <path d="M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19"/>
         <line x1="1" y1="1" x2="23" y2="23"/>
       </svg>
       Hide Common`;
}

// ============================================================
// Photo on demand (called from inline onclick)
// ============================================================
window.loadPhotoForCard = async function(flightId, btn) {
  const flight = state.flights.find(f => f.id === flightId);
  if (!flight) return;

  const reg = flight.aircraft.reg;
  const modes = flight.aircraft.modeS;
  if (!reg && !modes) {
    showToast('No registration available for photo lookup');
    return;
  }

  btn.textContent = '⏳ Loading…';
  btn.disabled = true;

  const urls = [];
  if (reg) urls.push(`https://api.planespotters.net/pub/photos/reg/${reg.replace(/-/g, '')}`);
  if (modes) urls.push(`https://api.planespotters.net/pub/photos/hex/${modes.toLowerCase()}`);

  for (const url of urls) {
    try {
      const resp = await fetch(url);
      if (!resp.ok) continue;
      const data = await resp.json();
      const photos = data.photos || [];
      if (photos.length > 0) {
        const p = photos[0];
        const thumb = p.thumbnail_large || p.thumbnail || {};
        flight.photo = {
          url: thumb.src,
          thumbnail: thumb.src,
          link: p.link,
          photographer: p.photographer,
        };

        // Update just this card's photo section
        const photoEl = document.getElementById(`photo-${flightId}`);
        if (photoEl) {
          const imgSrc = flight.photo.url;
          const creditName = flight.photo.photographer || 'Planespotters.net';
          const creditLink = flight.photo.link || 'https://www.planespotters.net';
          photoEl.innerHTML = `
            <img src="${esc(imgSrc)}" alt="Aircraft photo" loading="lazy">
            <div class="card-photo-credit">
              <a href="${esc(creditLink)}" target="_blank" rel="noopener">📷 ${esc(creditName)}</a>
            </div>
          `;
        }
        showToast('📸 Photo loaded!');
        return;
      }
    } catch { /* try next */ }
  }
  showToast('📷 No photo found on Planespotters');
  btn.textContent = 'No Photo Found';
};

window.copyPreset = function(json, name) {
  copyToClipboard(json, `Copied ${name} JSON!`);
};

// ============================================================
// Modal
// ============================================================
function openModal() {
  const overlay = document.getElementById('modal-overlay');
  overlay.hidden = false;
  document.body.style.overflow = 'hidden';
  document.getElementById('modal-close').focus();
}

function closeModal() {
  const overlay = document.getElementById('modal-overlay');
  overlay.hidden = true;
  document.body.style.overflow = '';
}

// ============================================================
// Data loading
// ============================================================
async function loadData() {
  const loadingEl = document.getElementById('loading-state');
  const gridEl = document.getElementById('flights-grid');
  const emptyEl = document.getElementById('empty-state');

  loadingEl.style.display = 'flex';
  gridEl.hidden = true;
  emptyEl.hidden = true;

  try {
    // Load arrivals and airports config in parallel
    const [arrivalsResp, airportsResp] = await Promise.all([
      fetch(`data/arrivals.json?_=${Date.now()}`),
      fetch(`config/airports.json?_=${Date.now()}`),
    ]);

    const arrivals = await arrivalsResp.json();
    const airportsConfig = await airportsResp.json();

    state.flights = arrivals.flights || [];
    state.meta = arrivals._meta || {};
    state.airports = state.meta.airports || airportsConfig.active || [];
    state.presets = airportsConfig.presets || [];

    // Header
    renderAirportPills(state.airports);
    renderDateBanner(state.meta);
    renderLastUpdated(state.meta);

    // Modal
    renderModal(state.airports, state.presets);

    loadingEl.style.display = 'none';
    renderAll();

  } catch (err) {
    console.error('Failed to load flight data:', err);
    loadingEl.innerHTML = `
      <div class="empty-icon">⚠️</div>
      <p style="color: var(--text-secondary)">Failed to load flight data.<br>
      <small style="color: var(--text-muted)">Make sure the GitHub Action has run at least once and GitHub Pages is active.<br>
      Error: ${esc(err.message)}</small></p>
    `;
  }
}

// ============================================================
// Event listeners
// ============================================================
function attachEventListeners() {
  // Rarity pills
  document.querySelectorAll('.rarity-pill').forEach(btn => {
    btn.addEventListener('click', () => {
      state.activeRarity = btn.dataset.rarity;
      renderAll();
    });
  });

  // Time tabs
  document.querySelectorAll('[data-time]').forEach(btn => {
    btn.addEventListener('click', () => {
      state.activeTime = btn.dataset.time;
      renderAll();
    });
  });

  // Hide common toggle
  document.getElementById('btn-toggle-common').addEventListener('click', () => {
    state.hideCommon = !state.hideCommon;
    // If enabling hide-common and rarity is 'Common', reset to 'all'
    if (state.hideCommon && state.activeRarity === 'Common') {
      state.activeRarity = 'all';
    }
    renderAll();
  });

  // Search
  let searchTimer;
  document.getElementById('search-input').addEventListener('input', e => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.searchQuery = e.target.value;
      renderAll();
    }, 180);
  });

  // Vacation modal
  document.getElementById('btn-vacation').addEventListener('click', openModal);
  document.getElementById('modal-close').addEventListener('click', closeModal);
  document.getElementById('modal-overlay').addEventListener('click', e => {
    if (e.target === e.currentTarget) closeModal();
  });

  // ESC key to close modal
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeModal();
  });

  // Reset filters
  document.getElementById('btn-reset-filters').addEventListener('click', () => {
    state.activeRarity = 'all';
    state.activeAirport = 'all';
    state.activeTime = 'all';
    state.hideCommon = false;
    state.searchQuery = '';
    document.getElementById('search-input').value = '';
    renderAll();
  });
}

// ============================================================
// Init
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
  attachEventListeners();
  loadData();
});
