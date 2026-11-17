/*! Spinn coffee maker — Home Assistant Lovelace cards
 *  Two custom cards, no build step, theme-aware (light/dark):
 *    - spinn-machine-card : illustrated machine + status + commands + favorites
 *    - spinn-recipe-card  : recipe browser with per-recipe iconography
 *  Part of https://github.com/spiegela/dizzycoffee
 */
"use strict";

const CARD_VERSION = "0.1.0";

/* -------------------------------------------------------------- shared maps */

// Consumable level enum -> fill fraction (docs/PROTOCOL.md §6).
const FILL_FRACTION = {
  EMPTY: 0, EMPTYORREMOVED: 0, REMOVED: 0,
  LEVEL0: 0.12, LEVEL1: 0.5, LEVEL2: 0.8,
  OK: 1, FULL: 1, PLACED: 1,
};
// Waste bins (grounds / drip tray): FULL is *bad*, empty is good.
const WASTE_FRACTION = {
  EMPTY: 0, OK: 0, PLACED: 0, LEVEL0: 0.2, LEVEL1: 0.5,
  LEVEL2: 0.8, FULL: 1, REMOVED: -1, EMPTYORREMOVED: -1,
};

const STATUS = {
  READY: { label: "Ready", tone: "ok" },
  ACTIVE: { label: "Ready", tone: "ok" },
  STANDBY: { label: "Standby", tone: "idle" },
  INACTIVE: { label: "Asleep", tone: "idle" },
  PREPAREDRINK: { label: "Brewing", tone: "busy", busy: true },
  CLEANING: { label: "Cleaning", tone: "info", busy: true },
  EXPELL: { label: "Expelling", tone: "info", busy: true },
  RECOVERING: { label: "Recovering", tone: "busy", busy: true },
  RECOVERY: { label: "Recovery", tone: "busy", busy: true },
  SPECIALTASK: { label: "Busy", tone: "info", busy: true },
  MACHINEERROR: { label: "Error", tone: "error" },
  UNDEFINED: { label: "—", tone: "idle" },
};

const TONE_COLOR = {
  ok: "var(--success-color, #43a047)",
  idle: "var(--disabled-text-color, #9e9e9e)",
  busy: "var(--warning-color, #ffa726)",
  info: "var(--info-color, #2196f3)",
  error: "var(--error-color, #e53935)",
};

/* ------------------------------------------------------------- recipe icons */
// Compact 48x48 glyphs. `currentColor` = outline (inherits text color);
// coffee/crema use theme-independent coffee tones so drinks read on any bg.
const COFFEE = "#7b5333";
const CREMA = "#c69c6d";

function cup({ bodyW = 22, fill = 0.55, crema = false, foam = false, tall = false }) {
  const x = (48 - bodyW) / 2;
  const top = tall ? 8 : 16;
  const bot = 38;
  const h = bot - top;
  const fillTop = bot - Math.max(0, Math.min(1, fill)) * (h - 3);
  const handle = tall ? "" :
    `<path d="M${x + bodyW} ${top + 4} q7 0 7 7 t-7 7" fill="none" stroke="currentColor" stroke-width="2.4"/>`;
  const cremaLine = crema
    ? `<rect x="${x + 2}" y="${fillTop - 2}" width="${bodyW - 4}" height="2.6" rx="1.3" fill="${CREMA}"/>`
    : "";
  const foamDome = foam
    ? `<path d="M${x + 1} ${top + 1} q${bodyW / 2} -9 ${bodyW - 2} 0 Z" fill="var(--spinn-foam, #f3ece2)" stroke="currentColor" stroke-width="1.4"/>`
    : "";
  return `
    <rect x="${x + 2}" y="${fillTop}" width="${bodyW - 4}" height="${bot - fillTop - 2}" rx="2.5" fill="${COFFEE}"/>
    ${cremaLine}
    <path d="M${x} ${top} h${bodyW} v${h - 6} q0 6 -6 6 h-${bodyW - 12} q-6 0 -6 -6 Z"
          fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round"/>
    ${handle}${foamDome}
    <rect x="${x - 4}" y="${bot + 1}" width="${bodyW + 8}" height="2.6" rx="1.3" fill="currentColor" opacity=".55"/>`;
}

function glassColdbrew() {
  return `
    <path d="M17 10 h14 l-2 28 q-.4 2 -5 2 t-5 -2 Z" fill="${COFFEE}" opacity=".9"/>
    <path d="M17 10 h14 l-2 28 q-.4 2 -5 2 t-5 -2 Z" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round"/>
    <rect x="19" y="14" width="6" height="6" rx="1.3" fill="#fff" opacity=".7"/>
    <rect x="25" y="20" width="6" height="6" rx="1.3" fill="#fff" opacity=".55"/>
    <rect x="28" y="4" width="2.6" height="20" rx="1.3" fill="currentColor" transform="rotate(12 29 14)"/>`;
}

function steam() {
  return `
    <g class="rx-steam" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" opacity=".5">
      <path d="M21 12 q-3 -4 0 -8"/><path d="M27 12 q3 -4 0 -8"/>
    </g>`;
}

const RECIPE_ICONS = {
  ristretto: () => cup({ bodyW: 16, fill: 0.4, crema: true }),
  espresso: () => cup({ bodyW: 20, fill: 0.55, crema: true }),
  doppio: () => cup({ bodyW: 28, fill: 0.6, crema: true }),
  lungo: () => cup({ bodyW: 20, fill: 0.8, tall: true }),
  americano: () => cup({ bodyW: 24, fill: 0.78, tall: true }),
  coldbrew: () => glassColdbrew(),
  coffee: () => cup({ bodyW: 26, fill: 0.78, tall: true }),
  cappuccino: () => cup({ bodyW: 24, fill: 0.5, foam: true }),
  latte: () => cup({ bodyW: 20, fill: 0.72, foam: true, tall: true }),
  macchiato: () => cup({ bodyW: 18, fill: 0.5, foam: true }),
  water: () => cup({ bodyW: 22, fill: 0.7 }) + steam(),
  default: () => cup({ bodyW: 22, fill: 0.55, crema: true }),
};

function recipeIconSvg(name, cls = "rx-icon") {
  const key = String(name || "").toLowerCase().replace(/[^a-z]/g, "");
  const draw = RECIPE_ICONS[key] || RECIPE_ICONS.default;
  return `<svg class="${cls}" viewBox="0 0 48 48" aria-hidden="true">${draw()}</svg>`;
}

/* -------------------------------------------------------- device illustration */
function machineSvg() {
  return `
  <svg class="machine-svg" viewBox="0 0 220 330" aria-hidden="true">
    <defs>
      <linearGradient id="metal" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stop-color="var(--spinn-metal-edge)"/>
        <stop offset=".12" stop-color="var(--spinn-metal-1)"/>
        <stop offset=".5" stop-color="var(--spinn-metal-2)"/>
        <stop offset=".88" stop-color="var(--spinn-metal-1)"/>
        <stop offset="1" stop-color="var(--spinn-metal-edge)"/>
      </linearGradient>
      <linearGradient id="panel" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stop-color="var(--spinn-panel-2)"/>
        <stop offset=".5" stop-color="var(--spinn-panel-1)"/>
        <stop offset="1" stop-color="var(--spinn-panel-2)"/>
      </linearGradient>
      <clipPath id="glassClip"><rect x="98" y="250" width="24" height="34" rx="3"/></clipPath>
    </defs>

    <!-- drip tray base -->
    <rect x="52" y="300" width="116" height="16" rx="6" fill="var(--spinn-metal-2)"/>
    <rect x="70" y="306" width="80" height="6" rx="3" fill="var(--spinn-metal-edge)" opacity=".7"/>

    <!-- body -->
    <rect x="46" y="54" width="128" height="250" rx="22" fill="url(#metal)" stroke="var(--spinn-metal-edge)" stroke-width="1.5"/>
    <!-- hopper band (beans) -->
    <path d="M46 76 v-0 a22 22 0 0 1 22 -22 h84 a22 22 0 0 1 22 22 v6 H46 Z" fill="var(--spinn-top)"/>
    <rect x="58" y="40" width="104" height="26" rx="12" fill="var(--spinn-hopper)" stroke="var(--spinn-metal-edge)" stroke-width="1"/>
    <g class="beans" fill="#3a2a1d">
      <circle cx="74" cy="53" r="3.3"/><circle cx="86" cy="50" r="3.3"/><circle cx="98" cy="54" r="3.3"/>
      <circle cx="110" cy="50" r="3.3"/><circle cx="122" cy="54" r="3.3"/><circle cx="134" cy="51" r="3.3"/>
      <circle cx="146" cy="54" r="3.3"/><circle cx="92" cy="57" r="3.3"/><circle cx="116" cy="57" r="3.3"/><circle cx="140" cy="58" r="3.1"/>
    </g>

    <!-- front panel -->
    <rect x="86" y="86" width="48" height="150" rx="10" fill="url(#panel)" opacity=".9"/>
    <!-- touch glyphs -->
    <g stroke="var(--spinn-glyph)" stroke-width="1.6" fill="none" opacity=".75">
      <circle cx="96" cy="100" r="3.2"/><circle cx="110" cy="100" r="3.2"/><circle cx="124" cy="100" r="3.2"/>
      <path d="M103 118 h14 v7 q0 4 -4 4 h-6 q-4 0 -4 -4 Z"/>
      <path d="M104 140 h12 v6 q0 4 -4 4 h-4 q-4 0 -4 -4 Z"/>
      <rect x="103" y="160" width="14" height="12" rx="2"/>
      <circle cx="110" cy="188" r="4"/><path d="M103 200 q7 -8 14 0"/>
    </g>

    <!-- logo ring (spins when busy) -->
    <g class="ring" transform="translate(110 222)">
      <circle r="15" fill="none" stroke="var(--spinn-glyph)" stroke-width="2" stroke-dasharray="2.4 3.2" opacity=".8"/>
      <text y="4" text-anchor="middle" class="wordmark">spinn</text>
    </g>

    <!-- spout -->
    <rect x="98" y="238" width="24" height="12" rx="3" fill="var(--spinn-metal-2)" stroke="var(--spinn-metal-edge)" stroke-width="1"/>
    <!-- pour stream (brewing only) -->
    <rect class="pour" x="108" y="250" width="4" height="30" rx="2" fill="${COFFEE}"/>

    <!-- glass + coffee -->
    <rect x="97" y="249" width="26" height="36" rx="4" fill="var(--spinn-glass)" stroke="var(--spinn-metal-edge)" stroke-width="1.4"/>
    <g clip-path="url(#glassClip)">
      <rect class="glass-coffee" x="98" y="284" width="24" height="0" fill="${COFFEE}"/>
      <rect class="glass-crema" x="98" y="284" width="24" height="2.4" fill="${CREMA}"/>
    </g>

    <!-- status lamp -->
    <circle class="lamp" cx="158" cy="70" r="4"/>
  </svg>`;
}

/* ------------------------------------------------------------------- helpers */
function fireMoreInfo(el, entityId) {
  if (!entityId) return;
  el.dispatchEvent(new CustomEvent("hass-more-info", {
    detail: { entityId }, bubbles: true, composed: true,
  }));
}

const SUFFIX = {
  status: ["sensor", "machine_status"],
  process: ["sensor", "process_status"],
  beans: ["sensor", "beans"],
  water: ["sensor", "water_tank"],
  water_volume: ["sensor", "water_volume"],
  grounds: ["sensor", "grounds_bin"],
  drip_tray: ["sensor", "drip_tray"],
  shot_count: ["sensor", "shot_count"],
  recipe_number: ["sensor", "recipe_number"],
  connected: ["binary_sensor", "connected"],
  brewing: ["binary_sensor", "brewing"],
  error: ["binary_sensor", "error"],
  recipe_select: ["select", "recipe_slot"],
  brew_button: ["button", "brew"],
  start_button: ["button", "start"],
  stop_button: ["button", "stop"],
  flush_button: ["button", "hopper_flush"],
};

function detectPrefix(hass) {
  if (!hass) return null;
  const hit = Object.keys(hass.states).find((e) => e.startsWith("sensor.") && e.endsWith("_machine_status"));
  if (!hit) return null;
  return hit.slice("sensor.".length, -"_machine_status".length);
}

function resolveEntities(hass, config) {
  const prefix = config.prefix || detectPrefix(hass);
  const out = {};
  for (const [key, [domain, suffix]] of Object.entries(SUFFIX)) {
    out[key] = config[key] || (prefix ? `${domain}.${prefix}_${suffix}` : null);
  }
  return out;
}

const stateStr = (hass, id) => (id && hass.states[id] ? hass.states[id].state : undefined);
const isOn = (hass, id) => stateStr(hass, id) === "on";

function levelBar(label, frac, tone) {
  const removed = frac < 0;
  const pct = Math.max(0, Math.min(1, removed ? 0 : frac)) * 100;
  return `
    <div class="gauge" title="${label}">
      <div class="gauge-track"><div class="gauge-fill tone-${tone}" style="width:${pct}%"></div></div>
      <div class="gauge-label">${label}${removed ? " · out" : ""}</div>
    </div>`;
}

function fillTone(frac) {
  if (frac <= 0.12) return "error";
  if (frac < 0.5) return "busy";
  return "ok";
}
function wasteTone(frac) {
  if (frac < 0) return "idle";
  if (frac >= 1) return "error";
  if (frac >= 0.8) return "busy";
  return "ok";
}

/* ------------------------------------------------------------- base element */
const BASE_CSS = `
  :host { --spinn-coffee: ${COFFEE}; display:block; }
  ha-card { display:block; padding: 16px; height: 100%; box-sizing: border-box;
    background: var(--ha-card-background, var(--card-background-color, #fff));
    border-radius: var(--ha-card-border-radius, 12px);
    box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,.12));
    color: var(--primary-text-color, #212121); }
  .row { display:flex; align-items:center; gap:10px; }
  .spacer { flex:1 1 auto; }
  .muted { color: var(--secondary-text-color); }
  button.sp { font: inherit; cursor:pointer; border:none; border-radius:12px;
    padding:9px 12px; display:inline-flex; align-items:center; gap:7px;
    background: var(--spinn-chip-bg); color: var(--primary-text-color);
    transition: transform .06s ease, background .15s ease, opacity .15s ease; }
  button.sp:hover { background: var(--spinn-chip-hover); }
  button.sp:active { transform: scale(.96); }
  button.sp:disabled { opacity:.38; cursor:not-allowed; }
  button.sp.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  button.sp .bi { width:18px; height:18px; display:inline-block; }
  .rx-icon { width:24px; height:24px; flex:0 0 auto; }
  svg.bi { width:18px; height:18px; }
  /* theme tokens */
  :host {
    --spinn-metal-1:#f4f5f7; --spinn-metal-2:#cfd3da; --spinn-metal-edge:#aab0ba;
    --spinn-panel-1:#eceef2; --spinn-panel-2:#dde0e6; --spinn-top:#d7dbe1;
    --spinn-hopper:#c9ccd3; --spinn-glyph:#8b9098; --spinn-glass:#eef2f6;
    --spinn-foam:#f3ece2;
    --spinn-chip-bg: var(--secondary-background-color, #e8eaed);
    --spinn-chip-hover: rgba(127,127,127,.18);
  }
  :host(.dark) {
    --spinn-metal-1:#4c515a; --spinn-metal-2:#2d3137; --spinn-metal-edge:#5b626d;
    --spinn-panel-1:#3b404a; --spinn-panel-2:#2f343c; --spinn-top:#383d45;
    --spinn-hopper:#2a2e34; --spinn-glyph:#aeb4be; --spinn-glass:#2b3038;
    --spinn-foam:#d8d2c7;
    --spinn-chip-hover: rgba(255,255,255,.12);
  }
  .tone-ok { background: ${TONE_COLOR.ok}; } .tone-busy { background: ${TONE_COLOR.busy}; }
  .tone-error { background: ${TONE_COLOR.error}; } .tone-idle { background: ${TONE_COLOR.idle}; }
  .tone-info { background: ${TONE_COLOR.info}; }
`;

class SpinnBase extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._built = false;
    if (this.shadowRoot) this.shadowRoot.innerHTML = "";
  }
  set hass(hass) {
    this._hass = hass;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.classList.toggle("dark", !!(hass.themes && hass.themes.darkMode));
    if (!this._built) this._build();
    this._update();
  }
  _onClick(ev) {
    const t = ev.composedPath().find((n) => n.dataset && n.dataset.action);
    if (!t) return;
    const { action, slot, entity } = t.dataset;
    this._handle(action, slot ? Number(slot) : undefined, entity);
  }
  async _press(entityId) {
    if (!entityId) return;
    await this._hass.callService("button", "press", { entity_id: entityId });
  }
  async _brewSlot(slot, name) {
    const e = this._ent;
    if (this._config.confirm && !window.confirm(`Brew ${name || "slot " + slot} now?`)) return;
    if (slot != null && e.recipe_select) {
      await this._hass.callService("select", "select_option", {
        entity_id: e.recipe_select, option: String(slot),
      });
    }
    await this._press(e.brew_button);
  }
}

/* ----------------------------------------------------- spinn-machine-card */
class SpinnMachineCard extends SpinnBase {
  static getStubConfig(hass) {
    const prefix = detectPrefix(hass);
    return { type: "custom:spinn-machine-card", prefix: prefix || "spinn" };
  }
  getCardSize() { return 8; }

  _build() {
    const css = `
      ${BASE_CSS}
      .top { margin-bottom: 6px; }
      .name { font-size: 1.15rem; font-weight: 600; }
      .status { font-weight:600; }
      .dot { width:9px; height:9px; border-radius:50%; display:inline-block; }
      .stage { display:flex; gap:16px; align-items:center; }
      .machine-svg { width: 150px; height: auto; flex:0 0 auto; filter: drop-shadow(0 6px 10px rgba(0,0,0,.18)); }
      :host(.offline) .machine-svg { opacity:.5; filter:grayscale(.6); }
      .meta { flex:1 1 auto; display:flex; flex-direction:column; gap:10px; min-width:0; }
      .gauge { display:flex; flex-direction:column; gap:4px; }
      .gauge-track { height:8px; border-radius:5px; background: var(--divider-color, #d0d0d0); overflow:hidden; }
      .gauge-fill { height:100%; border-radius:5px; transition: width .4s ease; }
      .gauge-label { font-size:.74rem; color: var(--secondary-text-color); }
      .controls { display:grid; grid-template-columns: repeat(2, 1fr); gap:8px; margin-top:14px; }
      .controls .wide { grid-column: 1 / -1; }
      .favs { display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }
      .fav { flex:0 0 auto; }
      .fav .rx-icon { width:22px; height:22px; color: var(--primary-text-color); }
      /* brewing animation */
      .ring { transform-origin:110px 222px; }
      :host(.busy) .ring { animation: spin 2.6s linear infinite; }
      @keyframes spin { to { transform: translate(110px,222px) rotate(360deg); } }
      .wordmark { font: 700 9px/1 Arial, sans-serif; fill: var(--spinn-glyph); letter-spacing:.3px; }
      .pour { opacity:0; }
      :host(.busy) .pour { opacity:1; animation: pour .9s ease-in-out infinite alternate; }
      @keyframes pour { from { transform: scaleY(.6); } to { transform: scaleY(1); } }
      .glass-coffee { transition: height .5s ease, y .5s ease; }
      .lamp { fill: ${TONE_COLOR.idle}; }
      @media (max-width:430px){ .stage{ flex-direction:column; } .machine-svg{ width:128px; } }
    `;
    this.shadowRoot.innerHTML = `
      <style>${css}</style>
      <ha-card>
        <div class="row top">
          <span class="name" data-action="more" data-what="status"></span>
          <span class="spacer"></span>
          <span class="dot status-dot"></span>
          <span class="status" data-action="more" data-what="status"></span>
        </div>
        <div class="stage">
          ${machineSvg()}
          <div class="meta"></div>
        </div>
        <div class="controls">
          <button class="sp primary wide" data-action="brew"><span class="bi">${recipeIconSvg("espresso","bi")}</span>Brew now</button>
          <button class="sp" data-action="start">▶ Start</button>
          <button class="sp" data-action="stop">■ Stop</button>
          <button class="sp wide" data-action="flush">⟳ Hopper flush</button>
        </div>
        <div class="favs"></div>
      </ha-card>`;
    this.shadowRoot.addEventListener("click", (e) => this._onClick(e));
    this._built = true;
  }

  _handle(action) {
    const e = this._ent;
    if (action === "brew") return this._brewSlot(null, "coffee");
    if (action === "start") return this._press(e.start_button);
    if (action === "stop") return this._press(e.stop_button);
    if (action === "flush") return this._press(e.flush_button);
    if (action === "more") return fireMoreInfo(this, e.status);
    if (action === "fav") { /* handled via dataset slot below */ }
  }
  _onClick(ev) {
    const t = ev.composedPath().find((n) => n.dataset && n.dataset.action);
    if (!t) return;
    const { action, slot, name } = t.dataset;
    if (action === "fav") return this._brewSlot(Number(slot), name);
    this._handle(action);
  }

  _update() {
    const hass = this._hass, cfg = this._config;
    const e = (this._ent = resolveEntities(hass, cfg));
    const root = this.shadowRoot;

    const rawStatus = (stateStr(hass, e.status) || "UNDEFINED").toUpperCase();
    const st = STATUS[rawStatus] || { label: rawStatus, tone: "idle" };
    const offline = e.connected && !isOn(hass, e.connected);
    const error = isOn(hass, e.error);
    const busy = !!st.busy || isOn(hass, e.brewing);

    this.classList.toggle("busy", busy && !offline);
    this.classList.toggle("offline", !!offline);

    root.querySelector(".name").textContent = cfg.name || (hass.states[e.status] && hass.states[e.status].attributes.friendly_name || "").replace(/ machine status$/i, "") || "Spinn";
    const statusEl = root.querySelector(".status");
    const tone = offline ? "idle" : error ? "error" : st.tone;
    statusEl.textContent = offline ? "Offline" : error ? "Error" : st.label;
    statusEl.style.color = TONE_COLOR[tone];
    root.querySelector(".status-dot").style.background = TONE_COLOR[tone];
    const lamp = root.querySelector(".lamp");
    if (lamp) lamp.style.fill = TONE_COLOR[tone];

    // coffee glass fill: full while brewing, else a hint when a drink sits ready
    const coffee = root.querySelector(".glass-coffee");
    const crema = root.querySelector(".glass-crema");
    if (coffee) {
      const level = busy ? 26 : rawStatus === "READY" || rawStatus === "ACTIVE" ? 0 : 0;
      coffee.setAttribute("height", level);
      coffee.setAttribute("y", 284 - level);
      if (crema) { crema.setAttribute("y", 284 - level - 2.4); crema.style.opacity = level > 0 ? 1 : 0; }
    }

    // gauges
    const meta = root.querySelector(".meta");
    const beans = (stateStr(hass, e.beans) || "").toUpperCase();
    const water = (stateStr(hass, e.water) || "").toUpperCase();
    const grounds = (stateStr(hass, e.grounds) || "").toUpperCase();
    const tray = (stateStr(hass, e.drip_tray) || "").toUpperCase();
    const vol = stateStr(hass, e.water_volume);
    const shots = stateStr(hass, e.shot_count);

    const bf = FILL_FRACTION[beans] ?? 1, wf = FILL_FRACTION[water] ?? 1;
    const gf = WASTE_FRACTION[grounds] ?? 0, tf = WASTE_FRACTION[tray] ?? 0;
    const waterLabel = "Water" + (vol && !isNaN(+vol) ? ` · ${vol} ml` : "");
    meta.innerHTML =
      levelBar("Beans", bf, fillTone(bf)) +
      levelBar(waterLabel, wf, fillTone(wf)) +
      levelBar("Grounds bin", gf < 0 ? 0 : gf, wasteTone(gf)) +
      levelBar("Drip tray", tf < 0 ? 0 : tf, wasteTone(tf)) +
      (shots && !isNaN(+shots) ? `<div class="muted" style="font-size:.78rem">☕ ${shots} shots total</div>` : "");

    // controls enable/disable
    const q = (s) => root.querySelector(s);
    const dis = (sel, v) => { const n = q(sel); if (n) n.disabled = v; };
    dis('[data-action="brew"]', offline || busy || !e.brew_button);
    dis('[data-action="start"]', offline || !e.start_button);
    dis('[data-action="stop"]', offline || !e.stop_button);
    dis('[data-action="flush"]', offline || busy || !e.flush_button);

    // favorites
    const favs = Array.isArray(cfg.favorites) ? cfg.favorites : [];
    const favWrap = root.querySelector(".favs");
    const sig = JSON.stringify(favs);
    if (favWrap.dataset.sig !== sig) {
      favWrap.dataset.sig = sig;
      favWrap.innerHTML = favs.map((f) =>
        `<button class="sp fav" data-action="fav" data-slot="${f.slot}" data-name="${f.name || "slot " + f.slot}">
           ${recipeIconSvg(f.icon || f.name)} ${f.name || "Slot " + f.slot}</button>`).join("");
    }
    favWrap.querySelectorAll(".fav").forEach((b) => (b.disabled = offline || busy || !e.brew_button || !e.recipe_select));
  }
}

/* ------------------------------------------------------ spinn-recipe-card */
const DEFAULT_RECIPES = [
  { slot: 1, name: "Ristretto", icon: "ristretto" },
  { slot: 2, name: "Espresso", icon: "espresso" },
  { slot: 3, name: "Doppio", icon: "doppio" },
  { slot: 4, name: "Lungo", icon: "lungo" },
  { slot: 5, name: "Americano", icon: "americano" },
  { slot: 6, name: "Cold Brew", icon: "coldbrew" },
];

class SpinnRecipeCard extends SpinnBase {
  static getStubConfig(hass) {
    return { type: "custom:spinn-recipe-card", prefix: detectPrefix(hass) || "spinn", recipes: DEFAULT_RECIPES };
  }
  getCardSize() { return 5; }

  _build() {
    const css = `
      ${BASE_CSS}
      .title { font-size:1.1rem; font-weight:600; margin-bottom:12px; display:flex; align-items:center; gap:8px; }
      .grid { display:grid; grid-template-columns: repeat(auto-fill, minmax(96px,1fr)); gap:10px; }
      .tile { border:none; cursor:pointer; border-radius:16px; padding:12px 8px 10px;
        display:flex; flex-direction:column; align-items:center; gap:6px; font:inherit;
        background: var(--spinn-chip-bg); color: var(--primary-text-color);
        transition: transform .07s ease, background .15s ease, box-shadow .15s ease; }
      .tile:hover { background: var(--spinn-chip-hover); }
      .tile:active { transform: scale(.95); }
      .tile:disabled { opacity:.4; cursor:not-allowed; }
      .tile.active { box-shadow: inset 0 0 0 2px var(--primary-color); }
      .tile .rx-icon { width:42px; height:42px; color: var(--primary-text-color); }
      .tile .rn { font-size:.86rem; font-weight:600; text-align:center; line-height:1.1; }
      .tile .rv { font-size:.72rem; color: var(--secondary-text-color); }
      .hint { margin-top:10px; font-size:.76rem; color: var(--secondary-text-color); }
    `;
    this.shadowRoot.innerHTML = `
      <style>${css}</style>
      <ha-card>
        <div class="title">${recipeIconSvg("coffee","rx-icon")} <span class="t-text">Recipes</span></div>
        <div class="grid"></div>
        <div class="hint"></div>
      </ha-card>`;
    this.shadowRoot.addEventListener("click", (e) => this._onClick(e));
    this._built = true;
  }

  _onClick(ev) {
    const t = ev.composedPath().find((n) => n.dataset && n.dataset.action === "recipe");
    if (!t || t.disabled) return;
    this._brewSlot(Number(t.dataset.slot), t.dataset.name);
  }

  _update() {
    const hass = this._hass, cfg = this._config;
    const e = (this._ent = resolveEntities(hass, cfg));
    const root = this.shadowRoot;
    const recipes = Array.isArray(cfg.recipes) && cfg.recipes.length ? cfg.recipes : DEFAULT_RECIPES;

    if (cfg.title) root.querySelector(".t-text").textContent = cfg.title;

    const offline = e.connected && !isOn(hass, e.connected);
    const busy = isOn(hass, e.brewing) || (stateStr(hass, e.status) || "").toUpperCase() === "PREPAREDRINK";
    const current = Number(stateStr(hass, e.recipe_select) ?? stateStr(hass, e.recipe_number));

    const grid = root.querySelector(".grid");
    const sig = JSON.stringify(recipes);
    if (grid.dataset.sig !== sig) {
      grid.dataset.sig = sig;
      grid.innerHTML = recipes.map((r) => `
        <button class="tile" data-action="recipe" data-slot="${r.slot}" data-name="${r.name || "Slot " + r.slot}">
          ${recipeIconSvg(r.icon || r.name)}
          <span class="rn">${r.name || "Slot " + r.slot}</span>
          ${r.volume ? `<span class="rv">${r.volume} ml</span>` : `<span class="rv">slot ${r.slot}</span>`}
        </button>`).join("");
    }
    grid.querySelectorAll(".tile").forEach((b) => {
      b.disabled = offline || busy || !e.brew_button;
      b.classList.toggle("active", Number(b.dataset.slot) === current);
    });

    root.querySelector(".hint").textContent = offline
      ? "Machine offline"
      : busy ? "Brewing…" : !e.recipe_select ? "No recipe selector found" : "Tap a recipe to brew";
  }
}

/* --------------------------------------------------------------- register */
customElements.define("spinn-machine-card", SpinnMachineCard);
customElements.define("spinn-recipe-card", SpinnRecipeCard);

window.customCards = window.customCards || [];
window.customCards.push(
  {
    type: "spinn-machine-card",
    name: "Spinn Machine",
    description: "Illustrated Spinn with status, consumables, and brew controls.",
    preview: true,
    documentationURL: "https://github.com/spiegela/dizzycoffee",
  },
  {
    type: "spinn-recipe-card",
    name: "Spinn Recipes",
    description: "A recipe browser that brews a cookbook slot on tap.",
    preview: true,
    documentationURL: "https://github.com/spiegela/dizzycoffee",
  }
);

console.info(`%c SPINN-CARDS %c v${CARD_VERSION} `,
  "color:#fff;background:#7b5333;border-radius:3px 0 0 3px;padding:1px 4px",
  "color:#7b5333;background:#f0e6da;border-radius:0 3px 3px 0;padding:1px 4px");
