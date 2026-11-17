/*! Spinn coffee maker — Home Assistant Lovelace cards
 *  Two custom cards, no build step, theme-aware (light/dark):
 *    - spinn-machine-card : illustrated machine + status + brew/stop + maintenance
 *    - spinn-recipe-card  : recipe browser with per-recipe iconography
 *  Part of https://github.com/spiegela/dizzycoffee
 */
"use strict";

const CARD_VERSION = "0.3.0";

/* -------------------------------------------------------------- shared maps */

// Consumable level enum -> fill fraction (docs/PROTOCOL.md §6).
const FILL_FRACTION = {
  EMPTY: 0, EMPTYORREMOVED: 0, REMOVED: 0,
  LEVEL0: 0.12, LEVEL1: 0.5, LEVEL2: 0.8,
  OK: 1, FULL: 1, PLACED: 1,
};
// Waste bins (grounds / drip tray): FULL is *bad*, empty is good. -1 = removed.
const WASTE_FRACTION = {
  EMPTY: 0, OK: 0, PLACED: 0, LEVEL0: 0.2, LEVEL1: 0.5,
  LEVEL2: 0.8, FULL: 1, REMOVED: -1, EMPTYORREMOVED: -1,
};

const STATUS = {
  READY: { label: "Ready", tone: "ok" },
  ACTIVE: { label: "Ready", tone: "ok" },
  STANDBY: { label: "Standby", tone: "idle" },
  INACTIVE: { label: "Asleep", tone: "idle" },
  PREPAREDRINK: { label: "Brewing", tone: "busy", busy: "brew" },
  CLEANING: { label: "Cleaning", tone: "info", busy: "clean" },
  EXPELL: { label: "Expelling", tone: "info", busy: "clean" },
  RECOVERING: { label: "Recovering", tone: "busy", busy: "other" },
  RECOVERY: { label: "Recovery", tone: "busy", busy: "other" },
  SPECIALTASK: { label: "Busy", tone: "info", busy: "other" },
  MACHINEERROR: { label: "Error", tone: "error" },
  UNDEFINED: { label: "—", tone: "idle" },
};

// ProcessStatus -> human phase (docs/PROTOCOL.md §6, observed live).
const PHASE = {
  WAITFORBREWERFILLSPEED: "Grinding & filling",
  WAITFOREXTRACTIONTIME: "Extracting",
};
function phaseLabel(raw) {
  if (!raw) return "";
  const k = String(raw).toUpperCase();
  if (k === "UNDEFINED" || k === "UNKNOWN" || k === "UNAVAILABLE") return "";
  if (PHASE[k]) return PHASE[k];
  return k.replace(/^WAITFOR/, "").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
}

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
  pourover: () => `
    <path d="M13 7 h22 l-7 11 h-8 Z" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round"/>
    <rect x="22.7" y="18.5" width="2.6" height="5" rx="1.2" fill="${COFFEE}"/>
    <rect x="15" y="28" width="18" height="8.5" rx="2" fill="${COFFEE}"/>
    <path d="M13 23 h22 v9.5 q0 6 -6 6 h-10 q-6 0 -6 -6 Z" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round"/>
    <rect x="9" y="40" width="30" height="2.6" rx="1.3" fill="currentColor" opacity=".55"/>`,
  carafe: () => `
    <path d="M12.6 29 h22.8 q.6 1.4 .6 2.6 q0 7.4 -7.4 7.4 h-9.2 q-7.4 0 -7.4 -7.4 q0 -1.2 .6 -2.6 Z" fill="${COFFEE}"/>
    <path d="M17 7 h14 v4.5 l-2 2.5 q8 5 8 17 q0 9 -8.5 9 h-9 q-8.5 0 -8.5 -9 q0 -12 8 -17 l-2 -2.5 Z"
          fill="none" stroke="currentColor" stroke-width="2.3" stroke-linejoin="round"/>
    <path d="M31 9 q8 1 7 11" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>`,
  mug: () => `
    <rect x="13" y="16" width="18" height="20.5" rx="2.5" fill="${COFFEE}"/>
    <path d="M11 10 h22 v24 q0 5 -5 5 h-12 q-5 0 -5 -5 Z" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round"/>
    <path d="M33 15 h3 q5 0 5 6 t-5 6 h-3" fill="none" stroke="currentColor" stroke-width="2.4"/>`,
  travelmug: () => `
    <path d="M16.5 15 h15 l-1.8 23 q-.2 2 -2.2 2 h-7 q-2 0 -2.2 -2 Z" fill="${COFFEE}" opacity=".9"/>
    <path d="M15 13 h18 l-2 25 q-.2 2.5 -2.7 2.5 h-8.6 q-2.5 0 -2.7 -2.5 Z" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linejoin="round"/>
    <rect x="13" y="7" width="22" height="6" rx="2.2" fill="currentColor"/>
    <rect x="15.6" y="22" width="16.8" height="7" rx="1" fill="currentColor" opacity=".35"/>`,
  default: () => cup({ bodyW: 22, fill: 0.55, crema: true }),
};

// Pick an icon for a recipe from an explicit icon, else its slug / name.
function iconFor(r) {
  if (!r) return "default";
  if (r.icon) return r.icon;
  const s = `${r.slug || ""} ${r.name || ""}`.toLowerCase();
  const rules = [
    [/hot.?water/, "water"], [/cold|iced|nitro/, "coldbrew"], [/americano/, "americano"],
    [/slow.?drip|pour/, "pourover"], [/carafe/, "carafe"], [/travel/, "travelmug"],
    [/doppio/, "doppio"], [/ristretto/, "ristretto"], [/lungo/, "lungo"],
    [/cappuccino/, "cappuccino"], [/latte/, "latte"], [/macchiato/, "macchiato"],
    [/espresso/, "espresso"], [/mug|xl/, "mug"], [/coffee/, "coffee"],
  ];
  if (r.cold) return "coldbrew";
  const hit = rules.find(([re]) => re.test(s));
  return hit ? hit[1] : "default";
}

// The machine's installed cookbook, published by the integration as the
// recipe-slot select's `recipes` attribute: [{slot, name, slug, drink_size, ...}].
function machineRecipes(hass, selectId) {
  const st = selectId && hass.states[selectId];
  const list = st && st.attributes && st.attributes.recipes;
  if (!Array.isArray(list)) return [];
  return list
    .filter((r) => r && r.slot != null && r.role !== "temp")
    .map((r) => ({ slot: Number(r.slot), role: r.role, name: r.name || `Slot ${r.slot}`, slug: r.slug, cold: r.cold,
      volume: r.drink_size || undefined, custom: r.type === "custom" }));
}

// Where a slot lives on the machine (0-3 user slots, 4/5/6 the cup buttons).
const ROLE_LABEL = { tall: "Tall cup button", medium: "Medium cup button", small: "Small cup button",
  user1: "User 1", user2: "User 2", user3: "User 3", user4: "User 4" };

// Config recipes/favorites may be full objects or bare slot numbers; fill the
// gaps (name, icon, volume) from the machine cookbook.
function normalizeRecipes(list, machine) {
  if (!Array.isArray(list)) return [];
  return list.map((item) => {
    const r = typeof item === "object" && item ? { ...item } : { slot: Number(item) };
    const m = machine.find((x) => x.slot === Number(r.slot)) || {};
    return { ...m, ...r, name: r.name || m.name || `Slot ${r.slot}`, volume: r.volume ?? m.volume };
  });
}

function recipeIconSvg(name, cls = "rx-icon") {
  const key = String(name || "").toLowerCase().replace(/[^a-z]/g, "");
  const draw = RECIPE_ICONS[key] || RECIPE_ICONS.default;
  // width/height attrs are a fallback; CSS on the class overrides them.
  return `<svg class="${cls}" viewBox="0 0 48 48" width="24" height="24" aria-hidden="true">${draw()}</svg>`;
}

// Small UI glyphs (24x24, stroke = currentColor).
const UI = {
  stop: `<svg class="bi" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2.5" fill="currentColor"/></svg>`,
  flush: `<svg class="bi" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 12a8 8 0 0 1 13.7-5.6M20 12a8 8 0 0 1-13.7 5.6"/><path d="M18 3v4h-4M6 21v-4h4"/></svg>`,
  clean: `<svg class="mi" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6v4H9zM10 7v3M14 7v3"/><path d="M7 10h10l1 11H6z"/></svg>`,
  descale: `<svg class="mi" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M12 3c-3.5 4.6-5.5 7.6-5.5 10.2a5.5 5.5 0 0 0 11 0C17.5 10.6 15.5 7.6 12 3z"/><path d="M9.5 14.5a2.6 2.6 0 0 0 2.5 2.4" stroke-linecap="round"/></svg>`,
  filter: `<svg class="mi" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M4 5h16l-6 8v5l-4 2v-7z"/></svg>`,
};

/* -------------------------------------------------------- device illustration
 * Modelled on the Spinn (original): an upright cylinder, a domed lid over a
 * smoked bean-hopper band, a full-height front strip carrying the touch panel
 * (4 status icons · small/medium/tall cup · user · spinn ring) above a recessed
 * dispensing bay (chevron spout, round cup grate) and a protruding drip tray.
 * Body: x 30..170, top ellipse cy=26. Front strip: x 58..142.
 */
const PANEL_X = { tank: 76, drops: 91, bean: 109, grate: 124 };
const PANEL_Y = { status: 69, small: 85, medium: 99, tall: 113, user: 127, ring: 149 };

function ringTicks(n = 44, r1 = 9.6, r2 = 12.6, period = 1.8) {
  let s = "";
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2 - Math.PI / 2;
    const c = Math.cos(a), sn = Math.sin(a);
    const delay = ((i / n) * period - period).toFixed(3);
    s += `<line x1="${(c * r1).toFixed(2)}" y1="${(sn * r1).toFixed(2)}" x2="${(c * r2).toFixed(2)}" y2="${(sn * r2).toFixed(2)}" style="animation-delay:${delay}s"/>`;
  }
  return s;
}

function hopperBeans() {
  // three staggered rows of beans across the front of the band
  let s = "";
  const rows = [{ y: 47, off: 0 }, { y: 43, off: 4 }, { y: 39, off: 1.5 }];
  rows.forEach((r, ri) => {
    for (let x = 33 + r.off; x < 168; x += 7.2) {
      const rot = ((x * 37 + ri * 53) % 70) - 35;
      s += `<g transform="translate(${x.toFixed(1)} ${r.y}) rotate(${rot})"><ellipse rx="3" ry="2.1" fill="#4a3220"/><path d="M-2.2 0 q1.1 -.7 2.2 0 t2.2 0" stroke="#2a1a0f" stroke-width=".5" fill="none"/></g>`;
    }
  });
  return s;
}

function machineSvg() {
  return `
  <svg class="machine-svg" viewBox="0 0 200 300" aria-hidden="true">
    <defs>
      <linearGradient id="metal" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stop-color="var(--spinn-metal-3)"/>
        <stop offset=".08" stop-color="var(--spinn-metal-2)"/>
        <stop offset=".3" stop-color="var(--spinn-metal-1)"/>
        <stop offset=".62" stop-color="var(--spinn-metal-2)"/>
        <stop offset=".9" stop-color="var(--spinn-metal-3)"/>
        <stop offset="1" stop-color="var(--spinn-metal-edge)"/>
      </linearGradient>
      <linearGradient id="panel" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stop-color="var(--spinn-panel-2)"/>
        <stop offset=".35" stop-color="var(--spinn-panel-1)"/>
        <stop offset="1" stop-color="var(--spinn-panel-2)"/>
      </linearGradient>
      <linearGradient id="lid" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="var(--spinn-metal-1)"/>
        <stop offset="1" stop-color="var(--spinn-metal-2)"/>
      </linearGradient>
      <linearGradient id="bay" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="var(--spinn-bay-2)"/>
        <stop offset=".18" stop-color="var(--spinn-bay-1)"/>
        <stop offset="1" stop-color="var(--spinn-bay-2)"/>
      </linearGradient>
      <linearGradient id="smoke" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="var(--spinn-smoke)" stop-opacity=".95"/>
        <stop offset="1" stop-color="var(--spinn-smoke)" stop-opacity=".7"/>
      </linearGradient>
      <clipPath id="bandClip"><path d="M30 34 v16 a70 12 0 0 0 140 0 v-16 a70 12 0 0 1 -140 0 Z"/></clipPath>
      <clipPath id="glassClip"><path d="M85.6 195 L114.4 195 L112 227 L88 227 Z"/></clipPath>
    </defs>

    <!-- floor shadow -->
    <ellipse cx="100" cy="292" rx="74" ry="6" fill="#000" opacity=".13"/>

    <!-- body cylinder -->
    <path d="M30 48 V278 a70 12 0 0 0 140 0 V48 Z" fill="url(#metal)"/>
    <!-- smoked bean-hopper band (beans sink as the hopper empties) -->
    <path d="M30 34 v16 a70 12 0 0 0 140 0 v-16 a70 12 0 0 1 -140 0 Z" fill="url(#smoke)"/>
    <g clip-path="url(#bandClip)"><g class="beans">${hopperBeans()}</g></g>
    <path d="M32 40 a70 12 0 0 0 136 0" fill="none" stroke="#fff" stroke-opacity=".18" stroke-width="1.2"/>
    <!-- lid: rim band + domed top -->
    <path d="M30 26 v8 a70 12 0 0 0 140 0 v-8 a70 12 0 0 1 -140 0 Z" fill="url(#metal)"/>
    <ellipse cx="100" cy="26" rx="70" ry="12" fill="url(#lid)" stroke="var(--spinn-metal-edge)" stroke-width=".6"/>
    <ellipse cx="100" cy="25" rx="58" ry="8.6" fill="var(--spinn-lid-glass)" opacity=".55"/>

    <!-- full-height front strip -->
    <path d="M58 53 V285.5 a70 12 0 0 0 84 0 V53 Z" fill="url(#panel)"/>
    <path d="M58 53 V285.5 M142 53 V285.5" stroke="var(--spinn-metal-edge)" stroke-width=".7" opacity=".8"/>

    <!-- touch panel: status icons (light up on warnings) -->
    <g class="glyphs" fill="none" stroke-width=".85" stroke-linecap="round" stroke-linejoin="round">
      <g class="st st-tank" transform="translate(${PANEL_X.tank} ${PANEL_Y.status})">
        <path d="M-3.2 -3.2 V3.2 H3.2 V-3.2"/><path d="M-2.3 .6 q.77 -.9 1.53 0 t1.53 0 t1.53 0"/>
      </g>
      <g class="st st-drops" transform="translate(${PANEL_X.drops} ${PANEL_Y.status})">
        <path transform="translate(-1 .8) scale(.85)" d="M0 -3 C-1.8 -.6 -2.2 .4 -2.2 1.2 A2.2 2.2 0 0 0 2.2 1.2 C2.2 .4 1.8 -.6 0 -3Z"/>
        <path transform="translate(2.1 -1.6) scale(.5)" d="M0 -3 C-1.8 -.6 -2.2 .4 -2.2 1.2 A2.2 2.2 0 0 0 2.2 1.2 C2.2 .4 1.8 -.6 0 -3Z"/>
      </g>
      <g class="st st-bean" transform="translate(${PANEL_X.bean} ${PANEL_Y.status})">
        <ellipse cx=".6" cy=".7" rx="2.1" ry="2.8" transform="rotate(28 .6 .7)"/>
        <path d="M-.4 -1.5 q1.6 1.1 .6 2.2 t.8 2.1"/>
        <circle cx="-2.6" cy="-2.6" r=".45"/><circle cx="-1.2" cy="-3.5" r=".35"/>
      </g>
      <g class="st st-grate" transform="translate(${PANEL_X.grate} ${PANEL_Y.status})">
        <circle r="3.2"/><path d="M-2.3 -1.2 H2.3 M-2.9 0 H2.9 M-2.3 1.2 H2.3"/>
      </g>

      <!-- brew buttons: small / medium / tall cup, user -->
      <g class="pb pb-small" transform="translate(100 ${PANEL_Y.small})">
        <path d="M-3.2 -2 H1.8 V.3 Q1.8 2.3 -.2 2.3 H-1.2 Q-3.2 2.3 -3.2 .3 Z"/><path d="M1.8 -1.2 H2.5 A1 1 0 0 1 2.5 .8 H1.8"/>
      </g>
      <g class="pb pb-medium" transform="translate(100 ${PANEL_Y.medium})">
        <path d="M-3.7 -2.8 H2.5 V.6 Q2.5 3 .1 3 H-1.3 Q-3.7 3 -3.7 .6 Z"/><path d="M2.5 -1.8 H3.3 A1.2 1.2 0 0 1 3.3 .6 H2.5"/>
      </g>
      <g class="pb pb-tall" transform="translate(100 ${PANEL_Y.tall})">
        <path d="M-3.2 -4 H2.4 V3 Q2.4 4 1.4 4 H-2.2 Q-3.2 4 -3.2 3 Z"/><path d="M2.4 -2.2 H3.3 A1.5 1.5 0 0 1 3.3 .8 H2.4"/>
      </g>
      <g class="pb pb-user" transform="translate(100 ${PANEL_Y.user})">
        <circle cy="-1.5" r="1.7"/><path d="M-3.1 3.2 Q0 -.9 3.1 3.2"/>
        <g class="dots" stroke="none"><circle class="ud ud0" cx="-12.5" cy="2.4" r=".55"/><circle class="ud ud1" cx="-8.5" cy="2.4" r=".55"/><circle class="ud ud2" cx="8.5" cy="2.4" r=".55"/><circle class="ud ud3" cx="12.5" cy="2.4" r=".55"/></g>
      </g>
    </g>

    <!-- spinn ring: ticks sweep while brewing / cleaning -->
    <g class="ring" transform="translate(100 ${PANEL_Y.ring})">
      <g class="ticks">${ringTicks()}</g>
      <text y="1.9" text-anchor="middle" class="wordmark">spinn</text>
    </g>

    <!-- dispensing bay -->
    <rect x="62" y="172" width="76" height="92" fill="url(#bay)"/>
    <rect x="62" y="172" width="76" height="4" fill="#000" opacity=".12"/>
    <path d="M58 171.5 H142" stroke="var(--spinn-metal-edge)" stroke-width=".8"/>
    <!-- chevron spout -->
    <path d="M66 172 H134 L118 183 H82 Z" fill="var(--spinn-dark)"/>
    <rect x="96" y="182.5" width="8" height="3" rx="1" fill="var(--spinn-dark)"/>
    <!-- pour stream -->
    <rect class="pour" x="99" y="185" width="2" height="41" rx="1"/>
    <!-- glass -->
    <g clip-path="url(#glassClip)">
      <g class="glass-fill">
        <rect x="84" y="203" width="32" height="25" fill="${COFFEE}"/>
        <rect x="84" y="203" width="32" height="2.6" fill="${CREMA}"/>
      </g>
    </g>
    <path d="M85.6 195 L114.4 195 L112.2 226.4 Q112 228 110.4 228 L89.6 228 Q88 228 87.8 226.4 Z"
          fill="var(--spinn-glass)" stroke="var(--spinn-glass-edge)" stroke-width=".8"/>
    <path d="M88.6 198 L87.4 224" stroke="#fff" stroke-opacity=".45" stroke-width="1.1" stroke-linecap="round"/>
    <!-- round cup grate on its stem -->
    <rect x="70" y="229" width="60" height="3.4" fill="var(--spinn-dark)"/>
    <ellipse cx="100" cy="232.4" rx="30" ry="3.4" fill="var(--spinn-dark)"/>
    <ellipse cx="100" cy="229" rx="30" ry="3.4" fill="var(--spinn-dark-2)"/>
    <path d="M78 229 H122 M82 227.6 H118 M82 230.4 H118" stroke="var(--spinn-dark)" stroke-width=".6"/>
    <!-- lower housing inside the bay -->
    <path d="M64 240 Q100 236 136 240 V264 H64 Z" fill="url(#panel)" opacity=".9"/>
    <!-- drip tray (protrudes) + dark base -->
    <ellipse cx="100" cy="285" rx="40" ry="6.5" fill="var(--spinn-dark-2)"/>
    <path d="M55 266 v8 a45 8.5 0 0 0 90 0 v-8 a45 7.5 0 0 1 -90 0 Z" fill="url(#metal)" stroke="var(--spinn-metal-edge)" stroke-width=".5"/>
    <ellipse cx="100" cy="266" rx="45" ry="7.5" fill="var(--spinn-metal-1)" stroke="var(--spinn-metal-edge)" stroke-width=".5"/>
    <ellipse cx="100" cy="266" rx="37" ry="5.4" fill="var(--spinn-dark)"/>
    <path d="M70 264 H130 M66 266 H134 M70 268 H130" stroke="var(--spinn-dark-2)" stroke-width=".7"/>
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
  water_line: ["sensor", "water_line_status"],
  grounds: ["sensor", "grounds_bin"],
  drip_tray: ["sensor", "drip_tray"],
  shot_count: ["sensor", "shot_count"],
  recipe_number: ["sensor", "recipe_number"],
  deep_clean_count: ["sensor", "cups_since_deep_clean"],
  descale_count: ["sensor", "cups_since_descale"],
  filter_count: ["sensor", "filter_counter"],
  last_cleaning: ["sensor", "last_cleaning"],
  last_descaling: ["sensor", "last_descaling"],
  last_filter: ["sensor", "last_filter_change"],
  wifi: ["sensor", "wi_fi_signal"],
  catalog: ["sensor", "recipe_catalog"],
  connected: ["binary_sensor", "connected"],
  brewing: ["binary_sensor", "brewing"],
  cleaning: ["binary_sensor", "cleaning"],
  error: ["binary_sensor", "error"],
  recipe_select: ["select", "recipe_slot"],
  brew_button: ["button", "brew"],
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
    const id = config[key] || (prefix ? `${domain}.${prefix}_${suffix}` : null);
    out[key] = id && hass.states[id] ? id : (config[key] || null);
  }
  return out;
}

const BAD = new Set(["unknown", "unavailable", "", "none"]);
const stateStr = (hass, id) => {
  const s = id && hass.states[id] ? hass.states[id].state : undefined;
  return s === undefined || BAD.has(String(s).toLowerCase()) ? undefined : s;
};
const num = (hass, id) => { const v = stateStr(hass, id); return v !== undefined && !isNaN(+v) ? +v : undefined; };
const isOn = (hass, id) => stateStr(hass, id) === "on";

function ago(iso) {
  const t = Date.parse(iso);
  if (isNaN(t)) return null;
  const d = (Date.now() - t) / 86400000;
  if (d < 1) return "today";
  if (d < 2) return "yesterday";
  if (d < 60) return `${Math.floor(d)} days ago`;
  if (d < 730) return `${Math.round(d / 30.4)} months ago`;
  return `${Math.round(d / 365)} years ago`;
}

function wifiLabel(dbm) {
  if (dbm === undefined) return null;
  const q = dbm >= -55 ? "excellent" : dbm >= -67 ? "good" : dbm >= -75 ? "fair" : "weak";
  return `Wi-Fi ${q} (${dbm} dBm)`;
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function levelBar(label, frac, tone) {
  const pct = Math.max(0, Math.min(1, frac)) * 100;
  return `
    <div class="gauge" title="${esc(label)}">
      <div class="gauge-track"><div class="gauge-fill tone-${tone}" style="width:${pct}%"></div></div>
      <div class="gauge-label">${label}</div>
    </div>`;
}

function fillTone(frac) {
  if (frac <= 0.12) return "error";
  if (frac < 0.5) return "busy";
  return "ok";
}
function wasteTone(frac) {
  if (frac < 0) return "error";
  if (frac >= 1) return "error";
  if (frac >= 0.8) return "busy";
  return "ok";
}

/* ------------------------------------------------------------- base element */
const BASE_CSS = `
  :host { --spinn-coffee: ${COFFEE}; display:block; }
  [hidden] { display:none !important; }
  ha-card { display:block; padding: 16px; height: 100%; box-sizing: border-box;
    background: var(--ha-card-background, var(--card-background-color, #fff));
    border-radius: var(--ha-card-border-radius, 12px);
    box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,.12));
    color: var(--primary-text-color, #212121); }
  .row { display:flex; align-items:center; gap:10px; }
  .spacer { flex:1 1 auto; }
  .muted { color: var(--secondary-text-color); }
  button.sp { font: inherit; cursor:pointer; border:none; border-radius:12px;
    padding:9px 12px; display:inline-flex; align-items:center; justify-content:flex-start; gap:7px;
    background: var(--spinn-chip-bg); color: var(--primary-text-color);
    transition: transform .06s ease, background .15s ease, opacity .15s ease; }
  button.sp:hover { background: var(--spinn-chip-hover); }
  button.sp:active { transform: scale(.96); }
  button.sp:disabled { opacity:.38; cursor:not-allowed; }
  button.sp.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  button.sp.danger { background: ${TONE_COLOR.error}; color: #fff; }
  button.sp.small { padding:6px 10px; font-size:.82rem; border-radius:10px; }
  button.sp .bi, svg.bi { width:18px; height:18px; flex:0 0 auto; }
  .rx-icon { width:24px; height:24px; flex:0 0 auto; }
  /* theme tokens — light: brushed silver */
  :host {
    --spinn-metal-1:#f3f4f6; --spinn-metal-2:#cdd1d7; --spinn-metal-3:#adb3bb; --spinn-metal-edge:#8f969f;
    --spinn-panel-1:#e9ebee; --spinn-panel-2:#d4d8dd;
    --spinn-bay-1:#f1f2f4; --spinn-bay-2:#c9cdd3;
    --spinn-smoke:#3b2c22; --spinn-lid-glass:#c3c8ce;
    --spinn-dark:#2b2e33; --spinn-dark-2:#45494f;
    --spinn-glyph:#8a9099; --spinn-glyph-lit:#3d434b;
    --spinn-glass: rgba(255,255,255,.38); --spinn-glass-edge: rgba(110,120,132,.75);
    --spinn-foam:#f3ece2;
    --spinn-chip-bg: var(--secondary-background-color, #e8eaed);
    --spinn-chip-hover: rgba(127,127,127,.18);
  }
  /* dark: same silver machine, dimmed to sit on a dark dashboard */
  :host(.dark) {
    --spinn-metal-1:#a9aeb5; --spinn-metal-2:#80868e; --spinn-metal-3:#636970; --spinn-metal-edge:#50555c;
    --spinn-panel-1:#9a9fa6; --spinn-panel-2:#7d838a;
    --spinn-bay-1:#8d9299; --spinn-bay-2:#5f646b;
    --spinn-smoke:#24190f; --spinn-lid-glass:#5e646b;
    --spinn-dark:#1d1f23; --spinn-dark-2:#33363b;
    --spinn-glyph:#4c5259; --spinn-glyph-lit:#f4f6f8;
    --spinn-glass: rgba(255,255,255,.2); --spinn-glass-edge: rgba(220,226,232,.5);
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
const PANEL_BUTTONS = ["small", "medium", "tall", "user"];

class SpinnMachineCard extends SpinnBase {
  static getStubConfig(hass) {
    const prefix = detectPrefix(hass);
    return { type: "custom:spinn-machine-card", prefix: prefix || "spinn" };
  }
  getCardSize() { return 9; }

  _build() {
    const css = `
      ${BASE_CSS}
      .top { margin-bottom: 2px; }
      .name { font-size: 1.15rem; font-weight: 600; cursor:pointer; }
      .status { font-weight:600; cursor:pointer; }
      .dot { width:9px; height:9px; border-radius:50%; display:inline-block; }
      .sub { font-size:.8rem; color: var(--secondary-text-color); min-height:1.1em; margin-bottom:6px; }
      .stage { display:flex; gap:14px; align-items:center; }
      .machine-svg { width: 150px; height: auto; flex:0 0 auto; filter: drop-shadow(0 4px 8px rgba(0,0,0,.14)); }
      :host(.offline) .machine-svg { opacity:.55; filter:grayscale(.8); }
      .meta { flex:1 1 auto; display:flex; flex-direction:column; gap:10px; min-width:0; }
      .gauge { display:flex; flex-direction:column; gap:4px; }
      .gauge-track { height:8px; border-radius:5px; background: var(--divider-color, #d0d0d0); overflow:hidden; }
      .gauge-fill { height:100%; border-radius:5px; transition: width .4s ease; }
      .gauge-label { font-size:.74rem; color: var(--secondary-text-color); }
      .controls { display:flex; gap:8px; margin-top:14px; }
      .controls button { flex:1 1 auto; justify-content:center; font-weight:600; padding:11px 12px; }
      .favs { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }
      .fav .rx-icon { width:22px; height:22px; color: var(--primary-text-color); }
      .fav.current { box-shadow: inset 0 0 0 2px var(--primary-color); }
      /* maintenance */
      .maint { margin-top:14px; padding-top:12px; border-top:1px solid var(--divider-color, rgba(127,127,127,.25));
        display:flex; flex-direction:column; gap:9px; }
      .mhead { font-size:.78rem; font-weight:600; letter-spacing:.04em; text-transform:uppercase; color: var(--secondary-text-color); }
      .mrow { display:grid; grid-template-columns: 20px 1fr auto; align-items:center; column-gap:8px; row-gap:3px; cursor:pointer; }
      .mrow .mi { width:18px; height:18px; color: var(--secondary-text-color); }
      .mrow.due .mi { color: ${TONE_COLOR.busy}; }
      .mrow .ml { font-size:.86rem; }
      .mrow .mv { font-size:.78rem; color: var(--secondary-text-color); text-align:right; }
      .mrow .mbar { grid-column: 2 / -1; height:4px; border-radius:3px; background: var(--divider-color, #d0d0d0); overflow:hidden; }
      .mrow .mbar > div { height:100%; border-radius:3px; }
      .mfoot { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-top:2px; }
      .diag { font-size:.74rem; color: var(--secondary-text-color); }
      /* illustration states */
      .glyphs { stroke: var(--spinn-glyph); }
      .glyphs .dots { fill: var(--spinn-glyph); }
      .st, .pb { transition: stroke .3s ease; }
      .st.warn { stroke: ${TONE_COLOR.busy}; filter: drop-shadow(0 0 1.4px ${TONE_COLOR.busy}); }
      .st.alert { stroke: ${TONE_COLOR.error}; filter: drop-shadow(0 0 1.4px ${TONE_COLOR.error}); }
      :host(.awake) .pb { stroke: var(--spinn-glyph-lit); }
      .pb.lit { stroke: var(--primary-color); filter: drop-shadow(0 0 1.2px var(--primary-color)); }
      .pb.tap { cursor:pointer; }
      .ud.lit { fill: var(--primary-color); filter: drop-shadow(0 0 1px var(--primary-color)); }
      .ticks line { stroke: var(--spinn-glyph); stroke-width:.75; stroke-linecap:round; opacity:.55; }
      :host(.awake) .ticks line { stroke: var(--spinn-glyph-lit); opacity:.7; }
      :host(.busy) .ticks line { animation: tick 1.8s linear infinite; stroke: var(--spinn-ring-tone); }
      :host(.error) .ticks line { stroke: ${TONE_COLOR.error}; opacity:.9; }
      @keyframes tick { 0% { opacity:1; } 55% { opacity:.12; } 100% { opacity:.12; } }
      .wordmark { font: 700 5.6px/1 Arial, Helvetica, sans-serif; fill: var(--spinn-wordmark, #3a3f46); letter-spacing:.1px; }
      :host(.dark) .wordmark { fill: #1f2226; }
      .beans { transition: transform .6s ease; }
      .pour { fill: ${COFFEE}; opacity:0; transform-box: fill-box; transform-origin: top; }
      :host(.brewing) .pour { opacity:1; animation: pour .7s ease-in-out infinite alternate; }
      :host(.cleaning) .pour { opacity:.8; fill:#9fd0f5; animation: pour .5s ease-in-out infinite alternate; }
      @keyframes pour { from { transform: scaleY(.85); } to { transform: scaleY(1); } }
      .glass-fill { transform-box: fill-box; transform-origin: bottom; transform: scaleY(0); }
      :host(.brewing) .glass-fill { animation: fillup 24s cubic-bezier(.2,.6,.3,1) forwards; }
      @keyframes fillup { from { transform: scaleY(.04); } to { transform: scaleY(1); } }
      @media (prefers-reduced-motion: reduce) {
        :host(.busy) .ticks line, :host(.brewing) .pour, :host(.cleaning) .pour { animation: none; opacity: .9; }
        :host(.brewing) .glass-fill { animation: none; transform: scaleY(.6); }
      }
      @media (max-width:430px){ .stage{ flex-direction:column; } .machine-svg{ width:132px; } .meta{ width:100%; } }
    `;
    this.shadowRoot.innerHTML = `
      <style>${css}</style>
      <ha-card>
        <div class="row top">
          <span class="name" data-action="more"></span>
          <span class="spacer"></span>
          <span class="dot status-dot"></span>
          <span class="status" data-action="more"></span>
        </div>
        <div class="sub"></div>
        <div class="stage">
          ${machineSvg()}
          <div class="meta"></div>
        </div>
        <div class="controls">
          <button class="sp primary brew" data-action="brew"><span class="bi">${recipeIconSvg("espresso", "bi")}</span><span class="bl">Brew</span></button>
          <button class="sp danger stop" data-action="stop" hidden>${UI.stop}<span>Stop</span></button>
        </div>
        <div class="favs"></div>
        <div class="maint"></div>
      </ha-card>`;
    this.shadowRoot.addEventListener("click", (e) => this._onClick(e));
    this._built = true;
  }

  // Which slot each panel glyph brews. The cup buttons come from the machine's
  // cookbook roles (tall/medium/small = slots 4/5/6); `machine_buttons` in YAML
  // overrides, and `machine_buttons: false` turns the tap targets off.
  _panelMap() {
    const m = this._config.machine_buttons;
    if (m === false) return {};
    const auto = {};
    for (const r of this._machine()) if (["small", "medium", "tall"].includes(r.role)) auto[r.role] = r.slot;
    return { ...auto, ...(m && typeof m === "object" ? m : {}) };
  }

  // Idempotent: (re)points panel glyphs at their slots as the cookbook arrives.
  _wirePanelButtons() {
    const map = this._panelMap();
    for (const b of PANEL_BUTTONS) {
      const g = this.shadowRoot.querySelector(`.pb-${b}`);
      if (!g) continue;
      const slot = map[b];
      const on = slot != null;
      g.classList.toggle("tap", on);
      if (on) {
        g.dataset.action = "fav";
        g.dataset.slot = String(slot);
        if (!g.querySelector(".hit")) {
          // generous invisible hit area
          g.insertAdjacentHTML("afterbegin", `<rect class="hit" x="-7" y="-6" width="14" height="12" fill="transparent" stroke="none"/>`);
        }
      } else {
        delete g.dataset.action;
        delete g.dataset.slot;
      }
    }
  }

  _machine() {
    const sel = (this._ent || resolveEntities(this._hass, this._config)).recipe_select;
    return machineRecipes(this._hass, sel);
  }
  _lookup(slot) {
    const machine = this._machine();
    const pool = [
      ...normalizeRecipes(this._config.favorites, machine),
      ...normalizeRecipes(this._config.recipes, machine),
      ...machine,
    ];
    return pool.find((r) => Number(r.slot) === Number(slot));
  }
  _slotName(slot) {
    const hit = this._lookup(slot);
    return hit && hit.name ? hit.name : `slot ${slot}`;
  }
  _slotIcon(slot) {
    const hit = this._lookup(slot);
    return hit ? iconFor(hit) : "espresso";
  }

  _onClick(ev) {
    const path = ev.composedPath();
    const t = path.find((n) => n.dataset && n.dataset.action);
    if (!t || t.disabled || (t.classList && t.classList.contains("off"))) return;
    const e = this._ent;
    const { action, slot, name, entity } = t.dataset;
    if (action === "fav") return this._brewSlot(Number(slot), name || this._slotName(slot));
    if (action === "brew") return this._brewSlot(null, this._currentSlot != null ? this._slotName(this._currentSlot) : "coffee");
    if (action === "stop") return this._press(e.stop_button);
    if (action === "flush") return this._press(e.flush_button);
    if (action === "more") return fireMoreInfo(this, entity || e.status);
  }

  _update() {
    const hass = this._hass, cfg = this._config;
    const e = (this._ent = resolveEntities(hass, cfg));
    const root = this.shadowRoot;

    const rawStatus = (stateStr(hass, e.status) || "UNDEFINED").toUpperCase();
    const st = STATUS[rawStatus] || { label: rawStatus, tone: "idle" };
    const offline = !!e.connected && stateStr(hass, e.connected) === "off";
    const error = isOn(hass, e.error) || rawStatus === "MACHINEERROR";
    const brewing = rawStatus === "PREPAREDRINK" || isOn(hass, e.brewing);
    const cleaning = st.busy === "clean" || isOn(hass, e.cleaning);
    const busy = !!st.busy || brewing || cleaning;
    const awake = !offline && ["READY", "ACTIVE"].includes(rawStatus);

    const tone = offline ? "idle" : error ? "error" : brewing ? "busy" : cleaning ? "info" : st.tone;
    this.classList.toggle("offline", offline);
    this.classList.toggle("busy", busy && !offline);
    this.classList.toggle("brewing", brewing && !offline);
    this.classList.toggle("cleaning", cleaning && !brewing && !offline);
    this.classList.toggle("error", error && !offline);
    this.classList.toggle("awake", (awake || busy) && !offline);
    this.style.setProperty("--spinn-ring-tone", TONE_COLOR[cleaning && !brewing ? "info" : "ok"]);

    // ---- header
    const friendly = hass.states[e.status] && hass.states[e.status].attributes.friendly_name;
    root.querySelector(".name").textContent = cfg.name || (friendly || "").replace(/ machine status$/i, "") || "Spinn";
    const statusEl = root.querySelector(".status");
    statusEl.textContent = offline ? "Offline" : error ? "Error" : brewing ? "Brewing" : cleaning ? st.label === "Expelling" ? "Expelling" : "Cleaning" : st.label;
    statusEl.style.color = TONE_COLOR[tone];
    root.querySelector(".status-dot").style.background = TONE_COLOR[tone];

    const sel = num(hass, e.recipe_select) ?? num(hass, e.recipe_number);
    this._currentSlot = sel;
    const phase = phaseLabel(stateStr(hass, e.process));
    let sub = "";
    if (offline) sub = "Not connected to Spinn cloud";
    else if (brewing) sub = [sel != null ? this._slotName(sel) : null, phase ? phase + "…" : "Preparing…"].filter(Boolean).join(" · ");
    else if (cleaning) sub = phase ? phase + "…" : "Running a cleaning cycle…";
    else if (error) sub = "Check the machine";
    else if (sel != null) sub = `Selected: ${this._slotName(sel)}`;
    const subEl = root.querySelector(".sub");
    subEl.textContent = sub;
    subEl.style.textTransform = "none";

    // ---- consumables
    const up = (id) => (stateStr(hass, id) || "").toUpperCase();
    const bf = FILL_FRACTION[up(e.beans)] ?? 1, wf = FILL_FRACTION[up(e.water)] ?? 1;
    const gf = WASTE_FRACTION[up(e.grounds)] ?? 0, tf = WASTE_FRACTION[up(e.drip_tray)] ?? 0;
    const vol = num(hass, e.water_volume);
    const shots = num(hass, e.shot_count);
    const out = (f) => (f < 0 ? " · removed" : "");
    root.querySelector(".meta").innerHTML =
      levelBar("Beans", bf, fillTone(bf)) +
      levelBar("Water" + (vol !== undefined ? ` · ${vol} ml` : ""), wf, fillTone(wf)) +
      levelBar("Grounds bin" + out(gf), gf < 0 ? 1 : gf, wasteTone(gf)) +
      levelBar("Drip tray" + out(tf), tf < 0 ? 1 : tf, wasteTone(tf)) +
      (shots !== undefined ? `<div class="muted" style="font-size:.78rem">${shots.toLocaleString()} shots brewed</div>` : "");

    // ---- illustration: hopper level + status icons + lit brew button
    const beansG = root.querySelector(".beans");
    if (beansG) beansG.setAttribute("transform", `translate(0 ${((1 - Math.max(0, bf)) * 16).toFixed(1)})`);

    const deepEvery = cfg.deep_clean_every ?? 100;
    const descaleEvery = cfg.descale_every ?? 500;
    const deepN = num(hass, e.deep_clean_count);
    const descN = num(hass, e.descale_count);
    const deepDue = deepEvery > 0 && deepN !== undefined && deepN >= deepEvery;
    const descDue = descaleEvery > 0 && descN !== undefined && descN >= descaleEvery;

    const setSt = (cls, level) => {
      const g = root.querySelector(`.st-${cls}`);
      if (!g) return;
      g.classList.toggle("warn", level === "warn");
      g.classList.toggle("alert", level === "alert");
    };
    const lvl = (frac) => (frac <= 0 ? "alert" : frac <= 0.12 ? "warn" : null);
    setSt("tank", offline ? null : lvl(wf));
    setSt("bean", offline ? null : lvl(bf));
    setSt("drops", offline ? null : descDue ? "warn" : null);
    const waste = Math.max(gf, tf);
    setSt("grate", offline ? null : gf < 0 || tf < 0 || waste >= 1 ? "alert" : waste >= 0.8 ? "warn" : null);

    this._wirePanelButtons();
    const map = this._panelMap();
    for (const b of PANEL_BUTTONS) {
      const g = root.querySelector(`.pb-${b}`);
      if (!g) continue;
      const mapped = map[b] != null;
      g.classList.toggle("lit", mapped && brewing && sel != null && Number(map[b]) === sel);
      g.classList.toggle("off", mapped && (offline || busy || !e.brew_button));
    }
    // user-slot dots (slots 0-3): mark the selected one; the person glyph lights with it
    const userSel = sel != null && sel >= 0 && sel <= 3 ? sel : null;
    root.querySelectorAll(".ud").forEach((d, i) => d.classList.toggle("lit", i === userSel));
    const person = root.querySelector(".pb-user");
    if (person && map.user == null) person.classList.toggle("lit", brewing && userSel != null);

    // ---- controls: Brew (idle) <-> Stop (busy)
    const brewBtn = root.querySelector(".brew");
    const stopBtn = root.querySelector(".stop");
    const showStop = busy && !offline && !!e.stop_button;
    brewBtn.hidden = showStop;
    stopBtn.hidden = !showStop;
    brewBtn.disabled = offline || busy || !e.brew_button;
    stopBtn.disabled = offline || !e.stop_button;
    const label = sel != null ? `Brew ${this._slotName(sel)}` : "Brew";
    brewBtn.querySelector(".bl").textContent = label;
    const iconKey = sel != null ? this._slotIcon(sel) : "espresso";
    if (brewBtn.dataset.icon !== iconKey) {
      brewBtn.dataset.icon = iconKey;
      brewBtn.querySelector(".bi").innerHTML = recipeIconSvg(iconKey, "bi");
    }

    // ---- favorites (quick-brew chips)
    const favs = normalizeRecipes(cfg.favorites, this._machine());
    const favWrap = root.querySelector(".favs");
    const sig = JSON.stringify(favs);
    if (favWrap.dataset.sig !== sig) {
      favWrap.dataset.sig = sig;
      favWrap.innerHTML = favs.map((f) =>
        `<button class="sp fav" data-action="fav" data-slot="${esc(f.slot)}" data-name="${esc(f.name)}">
           ${recipeIconSvg(iconFor(f))} ${esc(f.name)}</button>`).join("");
    }
    favWrap.hidden = favs.length === 0;
    favWrap.querySelectorAll(".fav").forEach((b) => {
      b.disabled = offline || busy || !e.brew_button || !e.recipe_select;
      b.classList.toggle("current", sel != null && Number(b.dataset.slot) === sel);
    });

    // ---- maintenance
    root.querySelector(".maint").innerHTML = cfg.maintenance === false ? "" : this._maintHtml({
      e, deepN, descN, deepEvery, descaleEvery, deepDue, descDue, offline, busy, cleaning,
    });
    root.querySelector(".maint").hidden = cfg.maintenance === false;
  }

  _maintHtml({ e, deepN, descN, deepEvery, descaleEvery, deepDue, descDue, offline, busy, cleaning }) {
    const hass = this._hass;
    const rows = [];
    const row = (icon, label, entity, count, every, due, lastId, unit = "cups") => {
      const last = stateStr(hass, lastId);
      const when = last ? ago(last) : null;
      if (count === undefined && !when) return;
      const parts = [];
      if (count !== undefined) parts.push(`${count.toLocaleString()} ${unit}`);
      if (when) parts.push(when);
      const bar = every > 0 && count !== undefined
        ? `<div class="mbar"><div class="tone-${due ? "busy" : count / every >= 0.8 ? "busy" : "ok"}" style="width:${Math.min(100, (count / every) * 100)}%"></div></div>`
        : "";
      rows.push(`
        <div class="mrow${due ? " due" : ""}" data-action="more" data-entity="${esc(entity || lastId || "")}">
          ${icon}<span class="ml">${label}${due ? " · due" : ""}</span><span class="mv">${parts.join(" · ")}</span>${bar}
        </div>`);
    };
    const cleanLabel = cleaning ? "Deep clean · running" : "Deep clean";
    row(UI.clean, cleanLabel, e.deep_clean_count, deepN, deepEvery, deepDue, e.last_cleaning);
    row(UI.descale, "Descale", e.descale_count, descN, descaleEvery, descDue, e.last_descaling);
    row(UI.filter, "Water filter", e.filter_count, num(hass, e.filter_count), 0, false, e.last_filter, "uses");

    const diag = [];
    const wl = stateStr(hass, e.water_line);
    if (wl) diag.push(/CONNECTED/i.test(wl) && !/DIS/i.test(wl) ? "Water line connected" : `Water line: ${wl.replace(/^WL_/, "").toLowerCase()}`);
    const wifi = wifiLabel(num(hass, e.wifi));
    if (wifi) diag.push(wifi);
    const fw = this._firmware(e.status);
    if (fw) diag.push(`fw ${fw}`);

    const flush = e.flush_button
      ? `<button class="sp small" data-action="flush" ${offline || busy ? "disabled" : ""}>${UI.flush}<span>Hopper flush</span></button>`
      : "";
    if (!rows.length && !flush && !diag.length) return "";
    return `
      <div class="mhead">Maintenance</div>
      ${rows.join("")}
      <div class="mfoot">${flush}<span class="spacer"></span><span class="diag">${esc(diag.join(" · "))}</span></div>`;
  }

  _firmware(statusId) {
    const hass = this._hass;
    try {
      const ent = hass.entities && hass.entities[statusId];
      const dev = ent && hass.devices && hass.devices[ent.device_id];
      return dev && dev.sw_version ? dev.sw_version : null;
    } catch (_) { return null; }
  }
}

/* ------------------------------------------------------ spinn-recipe-card */
// Only shown if neither YAML nor the integration supplies a cookbook.
const DEFAULT_RECIPES = [
  { slot: 0, name: "User slot 1", icon: "coffee" },
  { slot: 1, name: "User slot 2", icon: "coffee" },
  { slot: 2, name: "User slot 3", icon: "coffee" },
  { slot: 3, name: "User slot 4", icon: "coffee" },
  { slot: 4, name: "Tall cup", icon: "mug", role: "tall" },
  { slot: 5, name: "Medium cup", icon: "coffee", role: "medium" },
  { slot: 6, name: "Small cup", icon: "espresso", role: "small" },
];

class SpinnRecipeCard extends SpinnBase {
  static getStubConfig(hass) {
    // No recipes in the stub: the card reads the machine's installed cookbook.
    return { type: "custom:spinn-recipe-card", prefix: detectPrefix(hass) || "spinn" };
  }
  getCardSize() { return 5; }

  _build() {
    const css = `
      ${BASE_CSS}
      .title { font-size:1.1rem; font-weight:600; margin-bottom:12px; display:flex; align-items:center; gap:8px; }
      .title .rx-icon { width:24px; height:24px; color: var(--primary-text-color); }
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
        <div class="title">${recipeIconSvg("coffee", "rx-icon")} <span class="t-text">Recipes</span></div>
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
    // Source order: explicit YAML list > the machine's installed cookbook > generic demo set.
    const machine = machineRecipes(hass, e.recipe_select);
    const recipes = Array.isArray(cfg.recipes) && cfg.recipes.length
      ? normalizeRecipes(cfg.recipes, machine)
      : machine.length ? machine : DEFAULT_RECIPES;

    if (cfg.title) root.querySelector(".t-text").textContent = cfg.title;

    const status = (stateStr(hass, e.status) || "").toUpperCase();
    const offline = !!e.connected && stateStr(hass, e.connected) === "off";
    const busy = isOn(hass, e.brewing) || isOn(hass, e.cleaning) || !!(STATUS[status] && STATUS[status].busy);
    const current = num(hass, e.recipe_select) ?? num(hass, e.recipe_number);

    const grid = root.querySelector(".grid");
    const sig = JSON.stringify(recipes);
    if (grid.dataset.sig !== sig) {
      grid.dataset.sig = sig;
      grid.innerHTML = recipes.map((r) => `
        <button class="tile" data-action="recipe" data-slot="${esc(r.slot)}" data-name="${esc(r.name || "Slot " + r.slot)}" title="Slot ${esc(r.slot)}${r.custom ? " · your recipe" : ""}">
          ${recipeIconSvg(iconFor(r))}
          <span class="rn">${esc(r.name || "Slot " + r.slot)}</span>
          <span class="rv">${esc([r.volume ? `${r.volume} ml` : null, ROLE_LABEL[r.role] || (r.volume ? null : `slot ${r.slot}`)].filter(Boolean).join(" · "))}</span>
        </button>`).join("");
    }
    grid.querySelectorAll(".tile").forEach((b) => {
      b.disabled = offline || busy || !e.brew_button;
      b.classList.toggle("active", Number(b.dataset.slot) === current);
    });

    root.querySelector(".hint").textContent = offline
      ? "Machine offline"
      : busy ? (isOn(hass, e.cleaning) ? "Cleaning…" : "Brewing…")
        : !e.recipe_select ? "No recipe selector found" : "Tap a recipe to brew";
  }
}

/* ----------------------------------------------- spinn-recipe-editor-card */
// Browse every recipe (library, your customs, specials, milk guides), adjust it
// within its slider ranges, and brew once / save / install / delete. All writes
// go through the integration's spinn.* services.
const KIND_LABEL = { coffee: "Coffee", custom: "Mine", special: "Special", milk: "Milk" };
const FILTERS = [["all", "All"], ["coffee", "Coffee"], ["custom", "Mine"], ["special", "Specials"], ["milk", "Milk"]];
const SLOT_LABEL = (slot, role) => (ROLE_LABEL[role] ? ROLE_LABEL[role] : `Slot ${slot}`);

function mixColor(a, b, t) {
  const p = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const [x, y] = [p(a), p(b)];
  return "#" + x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, "0")).join("");
}

function previewCupSvg(r, vals) {
  const adj = r.adjust || {};
  const size = vals.size ?? (r.values || {}).size;
  let frac = 0.62;
  if (adj.size && size) frac = 0.28 + 0.72 * ((size - adj.size[0]) / Math.max(1, adj.size[1] - adj.size[0]));
  else if (r.cup_ml && size) frac = Math.min(1, size / r.cup_ml);
  frac = Math.max(0.12, Math.min(1, frac));
  const st = vals.strength ?? (r.values || {}).strength;
  const sFrac = adj.strength && st ? (st - adj.strength[0]) / Math.max(0.1, adj.strength[1] - adj.strength[0]) : 0.6;
  const coffee = mixColor("#b98a5e", "#3f2414", Math.max(0, Math.min(1, sFrac)));
  const top = 14, bot = 90, h = bot - top;
  const milk = r.kind === "milk";
  const fillTop = bot - frac * h;
  const coffeeTop = milk ? bot - Math.min(frac, 0.3) * h : fillTop;
  const ice = r.cold ? `
      <rect x="27" y="${fillTop + 6}" width="11" height="11" rx="2.5" fill="#fff" opacity=".55" transform="rotate(-12 32 ${fillTop + 11})"/>
      <rect x="41" y="${fillTop + 14}" width="10" height="10" rx="2.5" fill="#fff" opacity=".45" transform="rotate(16 46 ${fillTop + 19})"/>` : "";
  return `
    <svg class="pcup" viewBox="0 0 80 100" aria-hidden="true">
      <defs><clipPath id="pcClip"><path d="M15 ${top} H65 L60 ${bot} Q59.6 ${bot + 3} 56 ${bot + 3} H24 Q20.4 ${bot + 3} 20 ${bot} Z"/></clipPath></defs>
      <g clip-path="url(#pcClip)">
        ${milk ? `<rect class="pc-fill" x="10" y="${fillTop}" width="60" height="${bot - fillTop + 4}" fill="#e9dccb"/>
                  <rect class="pc-fill" x="10" y="${fillTop}" width="60" height="5" fill="#fbf7f1"/>` : ""}
        <rect class="pc-fill" x="10" y="${coffeeTop}" width="60" height="${bot - coffeeTop + 4}" fill="${coffee}"/>
        ${!milk ? `<rect class="pc-fill" x="10" y="${fillTop}" width="60" height="3" fill="${CREMA}" opacity=".9"/>` : ""}
        ${ice}
      </g>
      <path d="M15 ${top} H65 L60 ${bot} Q59.6 ${bot + 3} 56 ${bot + 3} H24 Q20.4 ${bot + 3} 20 ${bot} Z"
            fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round" opacity=".85"/>
      <path d="M19.5 20 L23 84" stroke="currentColor" stroke-opacity=".25" stroke-width="1.6" stroke-linecap="round"/>
    </svg>`;
}

class SpinnRecipeEditorCard extends SpinnBase {
  static getStubConfig(hass) {
    return { type: "custom:spinn-recipe-editor-card", prefix: detectPrefix(hass) || "spinn" };
  }
  getCardSize() { return 10; }

  setConfig(config) {
    super.setConfig(config);
    this._filter = (config && config.filter) || "all";
    this._sel = null;
    this._vals = {};
    this._mode = "";
    this._msg = "";
  }

  _build() {
    const css = `
      ${BASE_CSS}
      .hd { display:flex; align-items:center; gap:8px; margin-bottom:10px; }
      .hd .t { font-size:1.1rem; font-weight:600; }
      .hd .rx-icon { width:24px; height:24px; }
      .filters { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:10px; }
      .chip { font:inherit; font-size:.8rem; cursor:pointer; border:none; border-radius:999px; padding:5px 11px;
        background: var(--spinn-chip-bg); color: var(--primary-text-color); }
      .chip[aria-pressed="true"] { background: var(--primary-color); color: var(--text-primary-color, #fff); }
      .chip .n { opacity:.6; margin-left:3px; font-variant-numeric: tabular-nums; }
      .strip { display:grid; grid-auto-flow:column; grid-auto-columns: 84px; gap:8px; overflow-x:auto;
        padding: 2px 2px 8px; scroll-snap-type:x proximity; scrollbar-width: thin; }
      .tile { scroll-snap-align:start; border:none; cursor:pointer; border-radius:14px; padding:9px 6px 8px; font:inherit;
        display:flex; flex-direction:column; align-items:center; gap:5px; background: var(--spinn-chip-bg);
        color: var(--primary-text-color); position:relative; min-width:0; }
      .tile:hover { background: var(--spinn-chip-hover); }
      .tile[aria-pressed="true"] { box-shadow: inset 0 0 0 2px var(--primary-color); }
      .tile .rx-icon { width:32px; height:32px; }
      .tile .tn { font-size:.74rem; font-weight:600; line-height:1.15; text-align:center;
        display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
      .tile .pin { position:absolute; top:6px; right:7px; width:7px; height:7px; border-radius:50%; background: var(--primary-color); }
      .panel { margin-top:6px; padding-top:12px; border-top:1px solid var(--divider-color, rgba(127,127,127,.25)); }
      .hero { display:grid; grid-template-columns: 84px 1fr; gap:14px; align-items:start; }
      .pcup { width:84px; height:auto; color: var(--primary-text-color); }
      .pc-fill { transition: y .35s ease, height .35s ease, fill .35s ease; }
      .nm { font-size:1.12rem; font-weight:600; line-height:1.2; }
      .badges { display:flex; gap:6px; flex-wrap:wrap; margin:5px 0 6px; }
      .badge { font-size:.7rem; font-weight:600; letter-spacing:.03em; padding:2px 8px; border-radius:999px;
        background: var(--spinn-chip-bg); color: var(--secondary-text-color); }
      .badge.slot { background: color-mix(in srgb, var(--primary-color) 16%, transparent); color: var(--primary-color); }
      .badge.cold { background: color-mix(in srgb, var(--info-color, #039be5) 16%, transparent); color: var(--info-color, #039be5); }
      .note { font-size:.8rem; color: var(--secondary-text-color); line-height:1.4;
        display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; }
      .summary { font-size:.8rem; color: var(--secondary-text-color); margin-top:4px; font-variant-numeric: tabular-nums; }
      .need { margin-top:12px; }
      .need .lbl, .ctl .lbl { font-size:.74rem; font-weight:600; text-transform:uppercase; letter-spacing:.05em; color: var(--secondary-text-color); }
      .need ul { list-style:none; padding:0; margin:6px 0 0; display:flex; flex-wrap:wrap; gap:6px; }
      .need li { font-size:.78rem; padding:4px 9px; border-radius:8px; background: var(--spinn-chip-bg); }
      .ctls { display:flex; flex-direction:column; gap:12px; margin-top:14px; }
      .ctl .row1 { display:flex; align-items:baseline; justify-content:space-between; }
      .ctl .val { font-size:.9rem; font-weight:600; font-variant-numeric: tabular-nums; }
      .ctl .ends { display:flex; justify-content:space-between; font-size:.7rem; color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
      input[type=range] { -webkit-appearance:none; appearance:none; width:100%; height:22px; margin:4px 0 0;
        background:transparent; cursor:pointer; --pct: 50%; }
      input[type=range]::-webkit-slider-runnable-track { height:6px; border-radius:3px;
        background: linear-gradient(to right, var(--primary-color) var(--pct), var(--divider-color, rgba(127,127,127,.3)) var(--pct)); }
      input[type=range]::-moz-range-track { height:6px; border-radius:3px; background: var(--divider-color, rgba(127,127,127,.3)); }
      input[type=range]::-moz-range-progress { height:6px; border-radius:3px; background: var(--primary-color); }
      input[type=range]::-webkit-slider-thumb { -webkit-appearance:none; width:20px; height:20px; border-radius:50%; margin-top:-7px;
        background: var(--card-background-color, #fff); border:3px solid var(--primary-color); box-shadow: 0 1px 3px rgba(0,0,0,.25); }
      input[type=range]::-moz-range-thumb { width:14px; height:14px; border-radius:50%;
        background: var(--card-background-color, #fff); border:3px solid var(--primary-color); }
      input[type=range]:focus-visible { outline:2px solid var(--primary-color); outline-offset:3px; border-radius:4px; }
      .seg { display:inline-flex; border-radius:10px; overflow:hidden; background: var(--spinn-chip-bg); margin-top:6px; }
      .seg button { font:inherit; font-size:.8rem; border:none; padding:6px 12px; cursor:pointer; background:transparent; color: var(--primary-text-color); }
      .seg button[aria-pressed="true"] { background: var(--primary-color); color: var(--text-primary-color, #fff); }
      .fixed { font-size:.8rem; color: var(--secondary-text-color); margin-top:12px; }
      .acts { display:flex; flex-wrap:wrap; gap:8px; margin-top:16px; align-items:center; }
      .acts .grow { flex:1 1 auto; }
      button.link { font:inherit; font-size:.8rem; background:none; border:none; cursor:pointer; color: var(--primary-color); padding:4px; }
      button.link.danger { color: ${TONE_COLOR.error}; }
      .form { margin-top:12px; padding:12px; border-radius:12px; background: var(--spinn-chip-bg);
        display:flex; flex-direction:column; gap:10px; }
      .form label { font-size:.78rem; color: var(--secondary-text-color); display:flex; flex-direction:column; gap:4px; }
      .form input[type=text], .form select { font:inherit; padding:8px 10px; border-radius:8px; color: var(--primary-text-color);
        border:1px solid var(--divider-color, rgba(127,127,127,.35)); background: var(--card-background-color, #fff); }
      .form .row2 { display:flex; gap:8px; justify-content:flex-end; }
      .msg { font-size:.8rem; margin-top:10px; min-height:1.1em; color: var(--secondary-text-color); }
      .msg.err { color: ${TONE_COLOR.error}; }
      button.sp:focus-visible, .chip:focus-visible, .tile:focus-visible, .seg button:focus-visible { outline:2px solid var(--primary-color); outline-offset:2px; }
      @media (max-width:430px){ .hero { grid-template-columns: 64px 1fr; } .pcup { width:64px; } }
    `;
    this.shadowRoot.innerHTML = `
      <style>${css}</style>
      <ha-card>
        <div class="hd">${recipeIconSvg("pourover", "rx-icon")}<span class="t"></span></div>
        <div class="filters" role="group" aria-label="Recipe type"></div>
        <div class="strip" role="listbox" aria-label="Recipes"></div>
        <div class="panel"></div>
      </ha-card>`;
    const root = this.shadowRoot;
    root.addEventListener("click", (e) => this._click(e));
    root.addEventListener("input", (e) => this._input(e));
    this._built = true;
  }

  /* ---- data */
  _catalog() {
    const st = this._ent.catalog && this._hass.states[this._ent.catalog];
    const list = st && st.attributes && Array.isArray(st.attributes.recipes) ? st.attributes.recipes : [];
    const cookbook = st && Array.isArray(st.attributes.cookbook) ? st.attributes.cookbook : [];
    return { list, cookbook };
  }
  _rec(id) { return this._data.list.find((r) => r.id === id); }
  _installed(id) {
    return this._data.cookbook.filter((c) => c.recipe_id === id && c.role !== "temp");
  }
  _changed(r) {
    const v = r.values || {};
    return Object.keys(this._vals).some((k) => this._vals[k] !== undefined && this._vals[k] !== v[k]);
  }
  _effective(r) { return { ...(r.values || {}), ...this._vals }; }

  /* ---- render */
  _update() {
    const hass = this._hass, cfg = this._config;
    this._ent = resolveEntities(hass, cfg);
    this._data = this._catalog();
    const root = this.shadowRoot;
    root.querySelector(".t").textContent = cfg.title || "Recipe editor";

    const status = (stateStr(hass, this._ent.status) || "").toUpperCase();
    this._offline = !!this._ent.connected && stateStr(hass, this._ent.connected) === "off";
    this._busy = isOn(hass, this._ent.brewing) || isOn(hass, this._ent.cleaning) || !!(STATUS[status] && STATUS[status].busy);

    // pick up a just-saved recipe once it appears
    if (this._pendingName) {
      const hit = this._data.list.find((r) => r.kind === "custom" && r.name === this._pendingName);
      if (hit) { this._sel = hit.id; this._vals = {}; this._pendingName = null; this._filter = "all"; }
    }
    if (!this._sel || !this._rec(this._sel)) {
      const first = this._data.cookbook.find((c) => c.role !== "temp" && this._rec(c.recipe_id));
      this._sel = first ? first.recipe_id : (this._data.list[0] || {}).id || null;
      this._vals = {};
    }

    const sig = JSON.stringify([this._data.list.map((r) => [r.id, r.name]), this._data.cookbook, this._filter, this._sel]);
    if (sig !== this._sig) {
      this._sig = sig;
      this._renderFilters();
      this._renderStrip();
      this._renderPanel();
    }
    this._syncEnabled();
  }

  _renderFilters() {
    const counts = { all: this._data.list.length };
    for (const r of this._data.list) counts[r.kind] = (counts[r.kind] || 0) + 1;
    this.shadowRoot.querySelector(".filters").innerHTML = FILTERS
      .filter(([k]) => k === "all" || counts[k])
      .map(([k, label]) => `<button class="chip" data-act="filter" data-k="${k}" aria-pressed="${this._filter === k}">${label}<span class="n">${counts[k] || 0}</span></button>`)
      .join("");
  }

  _renderStrip() {
    const strip = this.shadowRoot.querySelector(".strip");
    const list = this._data.list.filter((r) => this._filter === "all" || r.kind === this._filter);
    if (!list.length) {
      strip.innerHTML = `<div class="muted" style="font-size:.85rem;padding:8px 2px">${this._data.list.length ? "No recipes of this type." : "Waiting for the recipe catalog from Spinn…"}</div>`;
      return;
    }
    strip.innerHTML = list.map((r) => `
      <button class="tile" role="option" data-act="pick" data-id="${esc(r.id)}" aria-pressed="${r.id === this._sel}" title="${esc(r.name)}">
        ${this._installed(r.id).length ? `<span class="pin" title="Installed in a slot"></span>` : ""}
        ${recipeIconSvg(iconFor(r))}<span class="tn">${esc(r.name)}</span>
      </button>`).join("");
    const cur = strip.querySelector('[aria-pressed="true"]');
    if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  _renderPanel() {
    const panel = this.shadowRoot.querySelector(".panel");
    const r = this._rec(this._sel);
    if (!r) { panel.innerHTML = ""; return; }
    const adj = r.adjust || {};
    const v = this._effective(r);
    const slots = this._installed(r.id);
    const badges = [
      `<span class="badge">${KIND_LABEL[r.kind] || r.kind}</span>`,
      ...slots.map((s) => `<span class="badge slot">${esc(SLOT_LABEL(s.slot, s.role))}</span>`),
      r.cold ? `<span class="badge cold">Cold</span>` : "",
      r.parent && r.kind !== "coffee" ? `<span class="badge">from ${esc(r.parent)}</span>` : "",
    ].join("");

    const ctl = (k, label, unit, step, fmt) => {
      const [lo, hi] = adj[k];
      const cur = v[k] ?? lo;
      return `
        <div class="ctl">
          <div class="row1"><span class="lbl">${label}</span><span class="val" data-val="${k}">${fmt(cur)}${unit}</span></div>
          <input type="range" id="rng-${k}" data-k="${k}" min="${lo}" max="${hi}" step="${step}" value="${cur}" aria-label="${label}"
                 style="--pct:${(((cur - lo) / Math.max(1e-9, hi - lo)) * 100).toFixed(1)}%">
          <div class="ends"><span>${fmt(lo)}${unit}</span><span>${fmt(hi)}${unit}</span></div>
        </div>`;
    };
    const f1 = (x) => (Math.round(x * 2) / 2).toFixed(1);
    const f0 = (x) => String(Math.round(x));
    const controls = [
      adj.strength ? ctl("strength", "Strength", " g", 0.5, f1) : "",
      adj.size ? ctl("size", "Size", " ml", 1, f0) : "",
      adj.balance ? ctl("balance", "Water balance", " %", 1, f0) : "",
      adj.order ? `
        <div class="ctl"><span class="lbl">Pour order</span><br>
          <div class="seg" role="group" aria-label="Pour order">
            <button data-act="order" data-v="1" aria-pressed="${v.coffee_first !== false}">Coffee first</button>
            <button data-act="order" data-v="0" aria-pressed="${v.coffee_first === false}">Water first</button>
          </div></div>` : "",
    ].join("");
    const adjustable = Object.keys(adj).length > 0;
    const fixedMsg = r.kind === "milk"
      ? "Brews a ristretto shot; finish it with the milk steps above."
      : "Fixed recipe: it brews as designed and can't be adjusted.";

    const items = (r.items || []);
    panel.innerHTML = `
      <div class="hero">
        <div class="cupwrap">${previewCupSvg(r, v)}</div>
        <div>
          <div class="nm">${esc(r.name)}</div>
          <div class="badges">${badges}</div>
          ${r.note ? `<div class="note">${esc(r.note)}</div>` : ""}
          <div class="summary" data-summary></div>
        </div>
      </div>
      ${items.length ? `<div class="need"><span class="lbl">${r.kind === "milk" ? "Steps &amp; ingredients" : "You'll also need"}</span><ul>${items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul></div>` : ""}
      ${adjustable ? `<div class="ctls">${controls}</div>` : `<div class="fixed">${fixedMsg}</div>`}
      <div class="acts">
        <button class="sp primary" data-act="brew">${recipeIconSvg(iconFor(r), "bi")}<span>Brew once</span></button>
        ${adjustable ? `<button class="sp" data-act="open" data-m="save">Save as…</button>` : ""}
        ${r.kind === "coffee" || r.kind === "custom" ? `<button class="sp" data-act="open" data-m="install">Put in slot…</button>` : ""}
        <span class="grow"></span>
        <button class="link" data-act="reset" hidden>Reset</button>
        ${r.kind === "custom" ? `<button class="link danger" data-act="open" data-m="delete">Delete</button>` : ""}
      </div>
      <div class="formwrap"></div>
      <div class="msg" role="status"></div>`;
    this._refreshLive();
    this._renderForm();
  }

  _slotOptions(selected) {
    const cb = this._data.cookbook.filter((c) => c.role !== "temp");
    const rows = cb.length ? cb : [0, 1, 2, 3, 4, 5, 6].map((s) => ({ slot: s, role: ["user1", "user2", "user3", "user4", "tall", "medium", "small"][s] }));
    return rows.map((c) => `<option value="${c.slot}" ${String(selected) === String(c.slot) ? "selected" : ""}>${esc(SLOT_LABEL(c.slot, c.role))}${c.name ? ` (now: ${esc(c.name)})` : ""}</option>`).join("");
  }

  _renderForm() {
    const wrap = this.shadowRoot.querySelector(".formwrap");
    if (!wrap) return;
    const r = this._rec(this._sel);
    if (!r || !this._mode) { wrap.innerHTML = ""; return; }
    if (this._mode === "save") {
      const base = r.kind === "custom" ? r.name : `My ${r.name}`;
      wrap.innerHTML = `
        <div class="form">
          <label>Name<input type="text" id="save-name" maxlength="40" value="${esc(base)}"></label>
          <label>Install in<select id="save-slot"><option value="">Don't install (keep in My recipes)</option>${this._slotOptions("")}</select></label>
          <div class="row2"><button class="sp" data-act="cancel">Cancel</button><button class="sp primary" data-act="save">Save recipe</button></div>
        </div>`;
    } else if (this._mode === "install") {
      const changed = this._changed(r);
      wrap.innerHTML = `
        <div class="form">
          ${changed ? `<div class="muted" style="font-size:.8rem">Your adjustments aren't saved yet. This installs ${esc(r.name)} as it is; use <b>Save as…</b> to install an adjusted version.</div>` : ""}
          <label>Put ${esc(r.name)} in<select id="inst-slot">${this._slotOptions(4)}</select></label>
          <div class="row2"><button class="sp" data-act="cancel">Cancel</button><button class="sp primary" data-act="install">Install</button></div>
        </div>`;
    } else if (this._mode === "delete") {
      wrap.innerHTML = `
        <div class="form">
          <div style="font-size:.88rem">Delete <b>${esc(r.name)}</b> from your Spinn account? This can't be undone.</div>
          <div class="row2"><button class="sp" data-act="cancel">Keep it</button><button class="sp danger" data-act="delete">Delete recipe</button></div>
        </div>`;
    }
    const first = wrap.querySelector("input, select");
    if (first) first.focus();
  }

  _refreshLive() {
    const root = this.shadowRoot;
    const r = this._rec(this._sel);
    if (!r) return;
    const v = this._effective(r);
    const cupwrap = root.querySelector(".cupwrap");
    if (cupwrap) cupwrap.innerHTML = previewCupSvg(r, v);
    const parts = [];
    if (v.size) parts.push(`${Math.round(v.size)} ml`);
    if (v.strength) parts.push(`${(Math.round(v.strength * 2) / 2).toFixed(1)} g coffee`);
    if (r.shots > 1) parts.push(`${r.shots} shots`);
    if (r.cup_ml) parts.push(`${r.cup_ml} ml cup`);
    const sum = root.querySelector("[data-summary]");
    if (sum) sum.textContent = parts.join(" · ");
    const reset = root.querySelector('[data-act="reset"]');
    if (reset) reset.hidden = !this._changed(r);
  }

  _syncEnabled() {
    const root = this.shadowRoot;
    const brew = root.querySelector('[data-act="brew"]');
    if (brew) {
      brew.disabled = this._offline || this._busy || this._working;
      brew.title = this._offline ? "Machine offline" : this._busy ? "Machine is busy" : "";
    }
    root.querySelectorAll('[data-act="save"],[data-act="install"],[data-act="delete"]').forEach((b) => { b.disabled = !!this._working; });
  }

  _say(text, err = false) {
    const m = this.shadowRoot.querySelector(".msg");
    if (!m) return;
    m.textContent = text;
    m.classList.toggle("err", err);
  }

  /* ---- events */
  _input(e) {
    const k = e.target && e.target.dataset && e.target.dataset.k;
    if (!k) return;
    const r = this._rec(this._sel);
    const num = Number(e.target.value);
    this._vals[k] = num;
    const lo = Number(e.target.min), hi = Number(e.target.max);
    e.target.style.setProperty("--pct", `${(((num - lo) / Math.max(1e-9, hi - lo)) * 100).toFixed(1)}%`);
    const lab = this.shadowRoot.querySelector(`[data-val="${k}"]`);
    if (lab) lab.textContent = k === "strength" ? `${(Math.round(num * 2) / 2).toFixed(1)} g` : k === "size" ? `${Math.round(num)} ml` : `${Math.round(num)} %`;
    if (r && (r.values || {})[k] === num) delete this._vals[k];
    this._refreshLive();
  }

  _payloadValues(r) {
    const v = this._effective(r), adj = r.adjust || {}, out = {};
    if (adj.strength && v.strength != null) out.strength_g = v.strength;
    if (adj.size && v.size != null) out.size_ml = v.size;
    if (adj.balance && v.balance != null) out.balance_pct = v.balance;
    if (adj.order && v.coffee_first != null) out.coffee_first = v.coffee_first;
    return out;
  }

  _device() {
    const ent = this._hass.entities && this._hass.entities[this._ent.catalog];
    return ent && ent.device_id ? { device_id: ent.device_id } : {};
  }

  async _call(service, data, okText) {
    this._working = true;
    this._syncEnabled();
    this._say("Working…");
    try {
      await this._hass.callService("spinn", service, { ...data, ...this._device() });
      this._say(okText);
      return true;
    } catch (err) {
      this._say((err && err.message) || "Something went wrong talking to Spinn.", true);
      return false;
    } finally {
      this._working = false;
      this._syncEnabled();
    }
  }

  async _click(e) {
    const t = e.composedPath().find((n) => n.dataset && n.dataset.act);
    if (!t || t.disabled) return;
    const act = t.dataset.act;
    const r = this._rec(this._sel);
    if (act === "filter") { this._filter = t.dataset.k; this._sig = null; return this._update(); }
    if (act === "pick") { this._sel = t.dataset.id; this._vals = {}; this._mode = ""; this._sig = null; return this._update(); }
    if (act === "order") { this._vals.coffee_first = t.dataset.v === "1"; if ((r.values || {}).coffee_first === this._vals.coffee_first) delete this._vals.coffee_first;
      t.parentNode.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === t))); return this._refreshLive(); }
    if (act === "reset") { this._vals = {}; return this._renderPanel(); }
    if (act === "open") { this._mode = this._mode === t.dataset.m ? "" : t.dataset.m; return this._renderForm(); }
    if (act === "cancel") { this._mode = ""; return this._renderForm(); }
    if (!r) return;
    if (act === "brew") {
      if (this._config.confirm && !window.confirm(`Brew ${r.name} now?`)) return;
      return this._call("brew_recipe", { recipe_id: r.id, ...this._payloadValues(r) },
        r.kind === "milk" ? `Pouring a ristretto for your ${r.name}…` : `Brewing ${r.name}…`);
    }
    if (act === "save") {
      const name = (this.shadowRoot.getElementById("save-name").value || "").trim();
      if (!name) return this._say("Give the recipe a name.", true);
      const slotV = this.shadowRoot.getElementById("save-slot").value;
      const data = { base_recipe_id: r.id, name, ...this._payloadValues(r) };
      if (slotV !== "") data.slot = Number(slotV);
      const ok = await this._call("save_recipe", data, slotV !== "" ? `Saved ${name} and put it in the slot.` : `Saved ${name} to My recipes.`);
      if (ok) { this._mode = ""; this._pendingName = name; this._renderForm(); }
      return;
    }
    if (act === "install") {
      const slot = Number(this.shadowRoot.getElementById("inst-slot").value);
      const ok = await this._call("install_recipe", { recipe_id: r.id, slot }, `Installed ${r.name}.`);
      if (ok) { this._mode = ""; this._renderForm(); }
      return;
    }
    if (act === "delete") {
      const ok = await this._call("delete_recipe", { recipe_id: r.id }, `Deleted ${r.name}.`);
      if (ok) { this._mode = ""; this._sel = null; this._sig = null; }
      return;
    }
  }
}

/* --------------------------------------------------------------- register */
if (!customElements.get("spinn-machine-card")) customElements.define("spinn-machine-card", SpinnMachineCard);
if (!customElements.get("spinn-recipe-card")) customElements.define("spinn-recipe-card", SpinnRecipeCard);
if (!customElements.get("spinn-recipe-editor-card")) customElements.define("spinn-recipe-editor-card", SpinnRecipeEditorCard);

window.customCards = window.customCards || [];
window.customCards.push(
  {
    type: "spinn-machine-card",
    name: "Spinn Machine",
    description: "Illustrated Spinn with live status, consumables, maintenance, and brew/stop controls.",
    preview: true,
    documentationURL: "https://github.com/spiegela/dizzycoffee",
  },
  {
    type: "spinn-recipe-card",
    name: "Spinn Recipes",
    description: "A recipe browser that brews a cookbook slot on tap.",
    preview: true,
    documentationURL: "https://github.com/spiegela/dizzycoffee",
  },
  {
    type: "spinn-recipe-editor-card",
    name: "Spinn Recipe Editor",
    description: "Browse every Spinn recipe, adjust strength and size, brew once, or save and install your own.",
    preview: true,
    documentationURL: "https://github.com/spiegela/dizzycoffee",
  }
);

console.info(`%c SPINN-CARDS %c v${CARD_VERSION} `,
  "color:#fff;background:#7b5333;border-radius:3px 0 0 3px;padding:1px 4px",
  "color:#7b5333;background:#f0e6da;border-radius:0 3px 3px 0;padding:1px 4px");
