/* Cape Town Wind Explorer — frontend.
 * Two nested precomputed domains per scenario: a metro "region" grid (200 m,
 * Cape Point to Durbanville to Stellenbosch) and a "detail" grid (75 m) over
 * the Table Mountain chain, blended by zoom. 16 directions, strong strength
 * only (the displayed field is near-linear in inflow — see
 * docs/ux-panel-analysis.md §0). The map shows street-level wind: 10 m AGL over
 * WorldCover roughness, with OSM tall-building canyon/downwash diagnostics.
 */
"use strict";

// Token comes from web/config.local.js (window.MAPBOX_TOKEN) — keep it out of app.js
const MAPBOX_TOKEN = window.MAPBOX_TOKEN || "YOUR_MAPBOX_TOKEN";
// Bump when web/data/* is regenerated so browsers refetch instead of caching.
const DATA_VERSION = "2026-06-22-stations";
const SECTOR_LABELS = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"];
const TRANSPARENT_PX = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=";
const GROUP_ORDER = ["City Bowl", "Atlantic Seaboard", "Southern Suburbs", "South Peninsula",
                     "Cape Flats", "Northern Suburbs", "Helderberg", "Winelands"];
const UPSCALE = { region: 3, detail: 5 };

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const state = {
  dirIdx: 6,            // SE
  strength: "strong",   // fixed: the top-10% blow (see docs/ux-panel-analysis.md §0)
  units: "kmh",
  opacity: 0.72,
  particles: !reduceMotion,
  threeD: false,
  group: "all",
  search: "",
  sort: { key: "score", asc: false },
};

/* ---------------- colormaps ---------------- */
const CMAPS = {
  grays: [[242,244,247],[196,202,210],[138,146,157],[78,87,100],[35,42,54]],
  turbo: [[48,18,59],[70,107,227],[40,170,225],[28,220,154],[124,251,71],[217,221,28],[252,160,5],[230,80,4],[160,25,2],[122,4,3]],
  inferno: [[0,0,4],[31,12,72],[85,15,109],[136,34,106],[186,54,85],[227,89,51],[249,140,10],[249,201,50],[252,255,164]],
  rdbu_r: [[5,48,97],[33,102,172],[67,147,195],[146,197,222],[224,236,244],[247,247,247],[253,219,199],[244,165,130],[214,96,77],[178,24,43],[103,0,31]],
};
function cmap(name, t) {
  const stops = CMAPS[name];
  const x = Math.min(Math.max(t, 0), 1) * (stops.length - 1);
  const k = Math.min(Math.floor(x), stops.length - 2);
  const f = x - k;
  const a = stops[k], b = stops[k + 1];
  return [a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]), a[2] + f * (b[2] - a[2])];
}
function cmapCss(name, t) {
  const c = cmap(name, t);
  return `rgb(${c[0] | 0},${c[1] | 0},${c[2] | 0})`;
}

// Single map layer: street-level wind. (Gusts / speed-up / turbulence /
// effect-zones were removed as map layers — the displayed field is near-linear
// in inflow and the colour scale auto-stretches, so the extra layers added
// clutter, not information. Gusts & turbulence live on as suburb-ranking inputs
// and in the hover probe / suburb popups.)
const OVERLAYS = {
  speed10: { label: "Street-level wind", cmap: "turbo", range: [0, 35], unit: "speed" },
};

/* ---------------- data ---------------- */
let STATIC = null, RUN = null, STATIONS = null, showStations = true;
const EMPTY_FC = { type: "FeatureCollection", features: [] };
let GRIDS = null;            // {region:{bbox,nx,ny,elev,dx_m}, detail:{...}}
const runCache = new Map();
const shelterCache = new Map();   // dirIdx -> {grid:{bbox,nx,ny}, factor}
let map = null, mapReady = false, loadSeq = 0;
let hoverFeatureId = null, popup = null;
let viewControl = null;     // map-corner 3D / animation toggles (synced to panel)

function b64ToU8(b64) {
  const bin = atob(b64);
  const u = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
  return u;
}
function dequant(field) {
  const u = b64ToU8(field.b64);
  const out = new Float32Array(u.length);
  const s = (field.max - field.min) / 255;
  for (let i = 0; i < u.length; i++) out[i] = field.min + u[i] * s;
  return out;
}
function gridFromStatic(s) {
  const [ny, nx] = s.shape;
  const u8 = b64ToU8(s.elevation_u16);
  const u16 = new Uint16Array(u8.buffer, u8.byteOffset, ny * nx);
  const elev = Float32Array.from(u16);
  return { bbox: s.bbox, nx, ny, elev, dx_m: s.dx_m };
}
function bilin(arr, g, fx, fy) {
  const x = Math.min(Math.max(fx, 0), g.nx - 1.001);
  const y = Math.min(Math.max(fy, 0), g.ny - 1.001);
  const x0 = Math.floor(x), y0 = Math.floor(y);
  const dx = x - x0, dy = y - y0;
  const i00 = y0 * g.nx + x0;
  return arr[i00] * (1 - dx) * (1 - dy) + arr[i00 + 1] * dx * (1 - dy)
       + arr[i00 + g.nx] * (1 - dx) * dy + arr[i00 + g.nx + 1] * dx * dy;
}
function lngLatToGrid(g, lng, lat) {
  const fx = (lng - g.bbox.lon_min) / (g.bbox.lon_max - g.bbox.lon_min) * g.nx - 0.5;
  const fy = (lat - g.bbox.lat_min) / (g.bbox.lat_max - g.bbox.lat_min) * g.ny - 0.5;
  return [fx, fy];
}
function gridToLngLat(g, fx, fy) {
  const lng = g.bbox.lon_min + (fx + 0.5) / g.nx * (g.bbox.lon_max - g.bbox.lon_min);
  const lat = g.bbox.lat_min + (fy + 0.5) / g.ny * (g.bbox.lat_max - g.bbox.lat_min);
  return [lng, lat];
}

async function loadRun(dirIdx, strength) {
  const key = `${dirIdx}_${strength}`;
  if (runCache.has(key)) return runCache.get(key);
  const resp = await fetch(`data/run_${String(dirIdx).padStart(2, "0")}_${strength}.json?v=${DATA_VERSION}`);
  if (!resp.ok) throw new Error(`run fetch failed: ${resp.status}`);
  const j = await resp.json();
  const run = { meta: j.meta, ranking: j.ranking, domains: {} };
  for (const [name, d] of Object.entries(j.domains)) {
    run.domains[name] = {
      speed10: dequant(d.fields.speed10),
      gust: dequant(d.fields.gust),     // hover probe + suburb popups
      speedup: dequant(d.fields.speedup),
      ti: dequant(d.fields.ti),         // probe + calm-pocket detection
      u10: dequant(d.fields.u10),
      v10: dequant(d.fields.v10),       // wind-flow particles
    };
  }
  run.ranking.forEach((r) => { r.score = windScore(r); });
  run.rankMap = new Map();
  [...j.ranking].sort((a, b) => b.score - a.score || b.speed10_mean - a.speed10_mean)
    .forEach((r, i) => run.rankMap.set(r.suburb, i + 1));
  if (runCache.size >= 10) runCache.delete(runCache.keys().next().value);  // LRU-ish
  runCache.set(key, run);
  return run;
}

async function loadShelter(dirIdx) {
  if (shelterCache.has(dirIdx)) return shelterCache.get(dirIdx);
  const resp = await fetch(`data/shelter_${String(dirIdx).padStart(2, "0")}.json?v=${DATA_VERSION}`);
  if (!resp.ok) throw new Error(`shelter fetch failed: ${resp.status}`);
  const j = await resp.json();
  const s = { grid: { bbox: j.bbox, nx: j.shape[1], ny: j.shape[0] }, factor: dequant(j.factor) };
  shelterCache.set(dirIdx, s);
  return s;
}

/* ---------------- windiness score ----------------
 * The ranking order. Transparent formula (also shown in the table's info
 * popover): 55% mean street wind (vs 20 m/s), 30% gusts (vs 30 m/s),
 * 15% turbulence (vs 0.7), each capped, scaled to 0-100.
 */
const SCORE = { wMean: 0.55, refMean: 20.0, wGust: 0.30, refGust: 30.0, wTi: 0.15, refTi: 0.7 };
function scoreParts(r) {
  return {
    mean: 100 * SCORE.wMean * Math.min(r.speed10_mean / SCORE.refMean, 1),
    gust: 100 * SCORE.wGust * Math.min(r.gust_mean / SCORE.refGust, 1),
    ti: 100 * SCORE.wTi * Math.min(r.ti_mean / SCORE.refTi, 1),
  };
}
function windScore(r) {
  const p = scoreParts(r);
  return Math.round(p.mean + p.gust + p.ti);
}
function scoreColor(s) {
  return `hsl(${Math.max(0, 120 - 1.55 * s)}, 68%, 42%)`;
}

/* Display range for the street-level wind colormap. It scales to the scenario's
 * inflow so land variation fills the palette (instead of sitting in the blue
 * bottom third of a fixed 0-35 m/s scale) and downslope jets reach red; the
 * open-sea inflow lands at a consistent ~0.6 of the scale across scenarios. */
function overlayRange() {
  if (!RUN) return OVERLAYS.speed10.range;
  return [0, Math.max(1.7 * RUN.meta.speed_10m, 12)];
}

/* ---------------- units ---------------- */
const UNITS = { kmh: { f: 3.6, lbl: "km/h", d: 0 }, ms: { f: 1, lbl: "m/s", d: 1 }, kt: { f: 1.944, lbl: "kt", d: 0 } };
function fmtSpeed(ms, withUnit = false) {
  const u = UNITS[state.units];
  return (ms * u.f).toFixed(u.d) + (withUnit ? " " + u.lbl : "");
}

const $ = (s) => document.querySelector(s);

/* ---------------- wind rose ---------------- */
function polar(cx, cy, r, deg) {
  const a = (deg * Math.PI) / 180;
  return [cx + r * Math.sin(a), cy - r * Math.cos(a)];
}
function petalPath(cx, cy, r0, r1, a1, a2) {
  const [x1, y1] = polar(cx, cy, r0, a1), [x2, y2] = polar(cx, cy, r1, a1);
  const [x3, y3] = polar(cx, cy, r1, a2), [x4, y4] = polar(cx, cy, r0, a2);
  return `M${x1},${y1} L${x2},${y2} A${r1},${r1} 0 0 1 ${x3},${y3} L${x4},${y4} A${r0},${r0} 0 0 0 ${x1},${y1} Z`;
}
function buildRose() {
  const cx = 140, cy = 140, R = 104, r0 = 18;
  const maxShare = Math.max(...STATIC.sectors.map((s) => Math.max(s.summer_share, s.winter_share)));
  let svg = `<svg viewBox="0 0 280 280" role="group" aria-label="wind direction compass">`;
  svg += `<circle cx="${cx}" cy="${cy}" r="${R}" fill="#fafbfd" stroke="#e3e8ee"/>`;
  for (const rr of [0.33, 0.66]) svg += `<circle cx="${cx}" cy="${cy}" r="${r0 + (R - r0 - 6) * rr}" fill="none" stroke="#eef1f5"/>`;
  for (let k = 0; k < 16; k++) {
    const s = STATIC.sectors[k], c = s.direction;
    const lenS = Math.sqrt(s.summer_share / maxShare) * (R - r0 - 6);
    const lenW = Math.sqrt(s.winter_share / maxShare) * (R - r0 - 6);
    svg += `<path class="petal" d="${petalPath(cx, cy, r0, r0 + lenW, c - 8.5, c + 8.5)}" fill="#3b82f6" opacity="0.5"/>`;
    svg += `<path class="petal" d="${petalPath(cx, cy, r0, r0 + lenS, c - 8.5, c + 8.5)}" fill="#f59e0b" opacity="0.55"/>`;
  }
  svg += `<path id="roseSel" d="" fill="rgba(79,70,229,.10)" stroke="#4f46e5" stroke-width="1.5"/>`;
  svg += `<g id="roseNeedle"></g>`;
  for (let k = 0; k < 16; k++) {
    const s = STATIC.sectors[k], c = s.direction;
    const tip = `${s.label} — ${Math.round(s.summer_share * 100)}% of summer hrs, ${Math.round(s.winter_share * 100)}% of winter · typical ${fmtSpeed(s.speed_median, true)}`;
    svg += `<path class="sector-hit" data-k="${k}" d="${petalPath(cx, cy, r0 - 6, R, c - 11.25, c + 11.25)}" fill="transparent"><title>${tip}</title></path>`;
  }
  for (const [lbl, ang] of [["N", 0], ["E", 90], ["S", 180], ["W", 270]]) {
    const [x, y] = polar(cx, cy, R + 12, ang);
    svg += `<text x="${x}" y="${y}" text-anchor="middle" dominant-baseline="central" font-size="12" font-weight="600" fill="#5b6573">${lbl}</text>`;
  }
  svg += `<circle cx="${cx}" cy="${cy}" r="${r0 - 4}" fill="#fff" stroke="#e3e8ee"/>`;
  svg += `<text id="roseDirLbl" x="${cx}" y="${cy}" text-anchor="middle" dominant-baseline="central" font-size="13" font-weight="700" fill="#18202b"></text>`;
  svg += `</svg>`;
  $("#rose").innerHTML = svg;
  $("#rose").querySelectorAll(".sector-hit").forEach((el) =>
    el.addEventListener("click", () => setDirection(+el.dataset.k)));
  updateRose();
}
function updateRose() {
  const cx = 140, cy = 140, R = 104, r0 = 18;
  const s = STATIC.sectors[state.dirIdx], c = s.direction;
  $("#roseSel").setAttribute("d", petalPath(cx, cy, r0 - 6, R, c - 11.25, c + 11.25));
  const [x1, y1] = polar(cx, cy, R + 4, c), [x2, y2] = polar(cx, cy, R - 26, c);
  const [hx1, hy1] = polar(cx, cy, R - 18, c - 4), [hx2, hy2] = polar(cx, cy, R - 18, c + 4);
  $("#roseNeedle").innerHTML =
    `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#dc2626" stroke-width="2.5" stroke-linecap="round"/>` +
    `<path d="M${x2},${y2} L${hx1},${hy1} L${hx2},${hy2} Z" fill="#dc2626"/>`;
  $("#roseDirLbl").textContent = s.label;
  $("#roseCaption").textContent = s.sparse
    ? `${s.label} rarely blows here — sparse record, overall speeds used. Map shows a strong blow.`
    : `Blows ${Math.round(s.summer_share * 100)}% of summer hours · ${Math.round(s.winter_share * 100)}% of winter. Map shows the strong blow (~${fmtSpeed(s.speed_p90, true)}); typical is ~${fmtSpeed(s.speed_median, true)}.`;
}

/* ---------------- map ---------------- */
function corners(bbox) {
  return [
    [bbox.lon_min, bbox.lat_max], [bbox.lon_max, bbox.lat_max],
    [bbox.lon_max, bbox.lat_min], [bbox.lon_min, bbox.lat_min],
  ];
}
/* Map-corner view control: 2D/3D terrain toggle (standard position, right under
 * zoom/compass). Wind-flow animation is always on, so it has no button. */
class ViewControl {
  onAdd() {
    this._c = document.createElement("div");
    this._c.className = "mapboxgl-ctrl mapboxgl-ctrl-group";
    this._b3d = this._btn("3D", "Toggle 3D terrain view", () => { toggleThreeD(); syncViewButtons(); });
    this._sync();
    return this._c;
  }
  _btn(label, title, fn) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.title = title;
    b.setAttribute("aria-label", title);
    b.className = "view-ctrl-btn";
    b.addEventListener("click", fn);
    this._c.appendChild(b);
    return b;
  }
  _sync() {
    this._b3d.classList.toggle("on", state.threeD);
  }
  onRemove() { this._c.remove(); }
}

function toggleThreeD() {
  state.threeD = !state.threeD;
  if (state.threeD) {
    if (!map.getSource("mapbox-dem"))
      map.addSource("mapbox-dem", { type: "raster-dem", url: "mapbox://mapbox.mapbox-terrain-dem-v1", tileSize: 512, maxzoom: 14 });
    map.setTerrain({ source: "mapbox-dem", exaggeration: 1.35 });
    map.easeTo({ pitch: 62, bearing: 132, duration: 1400 });
  } else {
    map.setTerrain(null);
    map.easeTo({ pitch: 0, bearing: 0, duration: 1000 });
  }
}

function initMap() {
  mapboxgl.accessToken = MAPBOX_TOKEN;
  const B = GRIDS.region.bbox;
  map = new mapboxgl.Map({
    container: "map",
    style: "mapbox://styles/mapbox/outdoors-v12",
    bounds: [[B.lon_min, B.lat_min], [B.lon_max, B.lat_max]],
    fitBoundsOptions: { padding: 10 },
    maxBounds: [[B.lon_min - 0.4, B.lat_min - 0.35], [B.lon_max + 0.4, B.lat_max + 0.35]],
  });
  map.addControl(new mapboxgl.NavigationControl({ visualizePitch: true }), "top-right");
  viewControl = new ViewControl();
  map.addControl(viewControl, "top-right");
  map.addControl(new mapboxgl.ScaleControl({ unit: "metric" }), "bottom-right");

  map.on("load", () => {
    const beforeId = map.getStyle().layers.find((l) => l.type === "symbol")?.id;

    map.addSource("field-region", { type: "image", url: TRANSPARENT_PX, coordinates: corners(GRIDS.region.bbox) });
    map.addLayer({ id: "field-region", type: "raster", source: "field-region",
      paint: { "raster-opacity": state.opacity, "raster-fade-duration": 120 } }, beforeId);
    map.addSource("field-detail", { type: "image", url: TRANSPARENT_PX, coordinates: corners(GRIDS.detail.bbox) });
    map.addLayer({ id: "field-detail", type: "raster", source: "field-detail",
      paint: { "raster-opacity": 0, "raster-fade-duration": 120 } }, beforeId);

    map.addSource("field-pockets", { type: "image", url: TRANSPARENT_PX, coordinates: corners(GRIDS.detail.bbox) });
    map.addLayer({ id: "field-pockets", type: "raster", source: "field-pockets",
      paint: { "raster-opacity": 0, "raster-fade-duration": 120 } }, beforeId);

    map.addSource("suburbs", { type: "geojson", data: { type: "FeatureCollection", features: [] }, promoteId: "name" });
    map.addLayer({
      id: "suburb-circles", type: "circle", source: "suburbs",
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 3.5, 14, 9],
        "circle-color": ["get", "color"],
        "circle-stroke-width": 1.5,
        "circle-stroke-color": ["case", ["boolean", ["feature-state", "hover"], false], "#4f46e5", "#ffffff"],
      },
    });
    map.addLayer({
      id: "suburb-labels", type: "symbol", source: "suburbs", minzoom: 11.4,
      layout: { "text-field": ["get", "name"], "text-size": 11, "text-offset": [0, 1.2], "text-anchor": "top" },
      paint: { "text-color": "#1f2937", "text-halo-color": "#ffffff", "text-halo-width": 1.4 },
    });
    map.addSource("landmarks", { type: "geojson", data: { type: "FeatureCollection",
      features: STATIC.landmarks.map((l) => ({ type: "Feature", properties: { name: `▲ ${l.name}` },
        geometry: { type: "Point", coordinates: [l.lon, l.lat] } })) } });
    map.addLayer({
      id: "landmark-labels", type: "symbol", source: "landmarks", minzoom: 9.2,
      layout: { "text-field": ["get", "name"], "text-size": 10.5, "text-font": ["DIN Pro Italic", "Arial Unicode MS Regular"] },
      paint: { "text-color": "#374151", "text-halo-color": "rgba(255,255,255,.85)", "text-halo-width": 1.2 },
    });

    // tall buildings (downwash sources)
    map.addSource("buildings", { type: "geojson", data: { type: "FeatureCollection",
      features: (STATIC.buildings || []).map((b) => ({ type: "Feature",
        properties: { h: b.height_m, name: b.name || "tall building" },
        geometry: { type: "Point", coordinates: [b.lon, b.lat] } })) } });
    map.addLayer({
      id: "buildings", type: "circle", source: "buildings", minzoom: 12.6,
      paint: { "circle-radius": 3, "circle-color": "#475569", "circle-stroke-width": 1,
               "circle-stroke-color": "#fff" },
    });
    map.on("click", "buildings", (e) => {
      const p = e.features[0].properties;
      new mapboxgl.Popup({ offset: 8 }).setLngLat(e.lngLat)
        .setHTML(`<div class="popup-title">${p.name}</div>
          <div class="popup-sub">≈ ${Math.round(p.h)} m tall — downwash can drive street-level gusts toward ~75% of roof-height wind</div>`)
        .addTo(map);
    });

    map.addSource("pocket-pins", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addLayer({
      id: "pocket-pins", type: "circle", source: "pocket-pins",
      layout: { visibility: "none" },
      paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 5.5, 14, 9],
               "circle-color": "#15803d", "circle-stroke-width": 2.2, "circle-stroke-color": "#ffffff" },
    });
    map.on("click", "pocket-pins", (e) => {
      const f = e.features[0];
      map.flyTo({ center: f.geometry.coordinates, zoom: Math.max(map.getZoom(), 14.3), speed: 1.6 });
      if (popup) popup.remove();
      popup = new mapboxgl.Popup({ offset: 10 }).setLngLat(f.geometry.coordinates)
        .setHTML(`<div class="popup-title">Calm pocket #${f.properties.n}</div>
          <div class="popup-sub">~${fmtSpeed(f.properties.speed, true)} at 25 m scale, while the open sea
          gets ${fmtSpeed(RUN.meta.speed_10m, true)}</div>`)
        .addTo(map);
    });
    map.on("mouseenter", "pocket-pins", () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", "pocket-pins", () => (map.getCanvas().style.cursor = ""));

    map.on("click", "suburb-circles", (e) => openSuburbPopup(e.features[0].properties.name));
    map.on("mouseenter", "suburb-circles", () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", "suburb-circles", () => (map.getCanvas().style.cursor = ""));
    map.on("mousemove", onProbeMove);
    map.getCanvas().addEventListener("mouseleave", () => ($("#probe").hidden = true));

    // Weather-station overlay: an arrow per PWS pointing downwind at the
    // OBSERVED aggregate bearing, coloured by how closely that bearing matches
    // the model here, for the hours the False Bay input blew from the selected
    // direction. Populated by updateStationSource() on every direction change.
    map.addImage("wind-arrow", makeArrowImage(), { sdf: true });
    map.addSource("stations", { type: "geojson", data: EMPTY_FC });
    map.addLayer({
      id: "station-halo", type: "circle", source: "stations",
      paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 5, 14, 8],
               "circle-color": "#ffffff", "circle-opacity": 0.85,
               "circle-stroke-width": 2, "circle-stroke-color": ["get", "color"] },
    });
    map.addLayer({
      id: "station-arrows", type: "symbol", source: "stations",
      filter: ["==", ["get", "hasDir"], true],
      layout: {
        "icon-image": "wind-arrow", "icon-rotate": ["get", "bearing"],
        "icon-rotation-alignment": "map", "icon-pitch-alignment": "map",
        "icon-allow-overlap": true, "icon-ignore-placement": true,
        "icon-size": ["interpolate", ["linear"], ["get", "size"], 1, 0.45, 4, 0.8, 9, 1.3],
      },
      paint: { "icon-color": ["get", "color"] },
    });
    map.on("click", "station-halo", openStationPopup);
    map.on("click", "station-arrows", openStationPopup);
    map.on("mouseenter", "station-halo", () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", "station-halo", () => (map.getCanvas().style.cursor = ""));

    mapReady = true;
    if (RUN) renderAll();
    map.once("idle", () => ($("#loading").style.display = "none"));
  });
  map.on("error", (e) => {
    if (!mapReady) $("#loading").innerHTML = `<p>⚠️ Map failed to load (${e.error?.message || "network/token issue"}).</p>`;
  });
}

/* ---------------- field overlay rendering ---------------- */
const offCanvas = document.createElement("canvas");
const bigCanvas = document.createElement("canvas");
// Cells of the region grid that the detail box covers — punched transparent
// so the region and detail layers never overlap (no opacity stacking / seam).
function detailHoleInRegion() {
  const R = GRIDS.region.bbox, D = GRIDS.detail.bbox, g = GRIDS.region;
  const lonr = R.lon_max - R.lon_min, latr = R.lat_max - R.lat_min;
  const c0 = Math.ceil((D.lon_min - R.lon_min) / lonr * g.nx);
  const c1 = Math.floor((D.lon_max - R.lon_min) / lonr * g.nx);
  const r0 = Math.ceil(g.ny - 0.5 - (D.lat_max - R.lat_min) / latr * g.ny);
  const r1 = Math.floor(g.ny - 0.5 - (D.lat_min - R.lat_min) / latr * g.ny);
  return { c0, c1, r0, r1 };
}

function drawDomainField(domKey) {
  const g = GRIDS[domKey], run = RUN.domains[domKey];
  const cmapName = OVERLAYS.speed10.cmap;
  offCanvas.width = g.nx; offCanvas.height = g.ny;
  const ctx = offCanvas.getContext("2d");
  const img = ctx.createImageData(g.nx, g.ny);
  const d = img.data;
  const arr = run.speed10;
  const [lo, hi] = overlayRange();
  for (let j = 0; j < g.ny; j++) {
    const row = g.ny - 1 - j;
    for (let i = 0; i < g.nx; i++) {
      const src = j * g.nx + i, dst = 4 * (row * g.nx + i);
      const c = cmap(cmapName, (arr[src] - lo) / (hi - lo));
      d[dst] = c[0]; d[dst + 1] = c[1]; d[dst + 2] = c[2]; d[dst + 3] = 255;
    }
  }
  // Region layer: punch a transparent hole where the detail box overlays it.
  if (domKey === "region") {
    const h = detailHoleInRegion();
    for (let r = Math.max(h.r0, 0); r < Math.min(h.r1, g.ny); r++) {
      for (let c = Math.max(h.c0, 0); c < Math.min(h.c1, g.nx); c++) {
        d[4 * (r * g.nx + c) + 3] = 0;
      }
    }
  }
  ctx.putImageData(img, 0, 0);
  const up = UPSCALE[domKey];
  bigCanvas.width = g.nx * up; bigCanvas.height = g.ny * up;
  const bctx = bigCanvas.getContext("2d");
  bctx.imageSmoothingEnabled = true;
  bctx.imageSmoothingQuality = "high";
  bctx.clearRect(0, 0, bigCanvas.width, bigCanvas.height);
  bctx.drawImage(offCanvas, 0, 0, bigCanvas.width, bigCanvas.height);
  return bigCanvas.toDataURL();
}
function renderField() {
  if (!mapReady || !RUN) return;
  // Single uniform opacity for both field layers. The region image has a
  // transparent hole where the detail box sits, and exactly ONE layer fills
  // that box (the 25 m micro field once the shelter file is loaded, otherwise
  // the 75 m detail field) — so the layers never overlap and there is no
  // opacity seam at the box edge.
  const op = state.opacity;
  map.getSource("field-region").updateImage({ url: drawDomainField("region") });
  map.setPaintProperty("field-region", "raster-opacity", op);

  const sh = shelterCache.get(state.dirIdx);
  if (sh) {
    drawMicro(sh);                                 // fills the box at 25 m
    map.getSource("field-detail").updateImage({ url: TRANSPARENT_PX });
    map.setPaintProperty("field-pockets", "raster-opacity", op);
    map.setPaintProperty("field-detail", "raster-opacity", 0);
  } else {
    map.getSource("field-detail").updateImage({ url: drawDomainField("detail") });
    map.getSource("field-pockets").updateImage({ url: TRANSPARENT_PX });
    map.setPaintProperty("field-detail", "raster-opacity", op);
    map.setPaintProperty("field-pockets", "raster-opacity", 0);
    setPinsVisible(false);
    // shelter file still loading: show 75 m now, swap to 25 m micro on arrival.
    const wanted = state.dirIdx;
    loadShelter(state.dirIdx)
      .then(() => { if (state.dirIdx === wanted && mapReady) renderField(); })
      .catch(console.error);
  }
}

/* 25 m micro layer: the 75 m solved street-level field redistributed by the
 * sub-grid shelter factor, so the wind map simply sharpens (200 m -> 75 m ->
 * 25 m) as you zoom. Calm-pocket pins are extracted along the way (low mean
 * AND low turbulence). */
function drawMicro(sh) {
  const g = sh.grid, det = RUN.domains.detail, dg = GRIDS.detail;
  const spec = OVERLAYS.speed10;
  const [lo, hi] = overlayRange();
  const ref = Math.max(RUN.meta.speed_10m, 0.1);
  offCanvas.width = g.nx; offCanvas.height = g.ny;
  const ctx = offCanvas.getContext("2d");
  const img = ctx.createImageData(g.nx, g.ny);
  const d = img.data;
  // precompute the affine 25 m -> 75 m fractional indices per row/column
  const fxs = new Float32Array(g.nx), fys = new Float32Array(g.ny);
  for (let i = 0; i < g.nx; i++) {
    const lon = g.bbox.lon_min + (i + 0.5) * (g.bbox.lon_max - g.bbox.lon_min) / g.nx;
    fxs[i] = (lon - dg.bbox.lon_min) / (dg.bbox.lon_max - dg.bbox.lon_min) * dg.nx - 0.5;
  }
  for (let j = 0; j < g.ny; j++) {
    const lat = g.bbox.lat_min + (j + 0.5) * (g.bbox.lat_max - g.bbox.lat_min) / g.ny;
    fys[j] = (lat - dg.bbox.lat_min) / (dg.bbox.lat_max - dg.bbox.lat_min) * dg.ny - 0.5;
  }
  const arr = det.speed10;
  const cand = [];
  for (let j = 0; j < g.ny; j++) {
    const row = g.ny - 1 - j;
    for (let i = 0; i < g.nx; i++) {
      const idx = j * g.nx + i, dst = 4 * (row * g.nx + i);
      const v = bilin(arr, dg, fxs[i], fys[j]) * sh.factor[idx];
      const c = cmap(spec.cmap, (v - lo) / (hi - lo));
      d[dst] = c[0]; d[dst + 1] = c[1]; d[dst + 2] = c[2]; d[dst + 3] = 255;
      if (v / ref < 0.33
          && bilin(det.ti, dg, fxs[i], fys[j]) < 0.45
          && bilin(dg.elev, dg, fxs[i], fys[j]) > 2) {
        cand.push([v / ref, i, j]);
      }
    }
  }
  ctx.putImageData(img, 0, 0);
  updatePocketPins(sh, cand, ref);
  bigCanvas.width = g.nx * 2; bigCanvas.height = g.ny * 2;
  const bctx = bigCanvas.getContext("2d");
  bctx.imageSmoothingEnabled = true;
  bctx.clearRect(0, 0, bigCanvas.width, bigCanvas.height);
  bctx.drawImage(offCanvas, 0, 0, bigCanvas.width, bigCanvas.height);
  const src = map.getSource("field-pockets");
  src.setCoordinates(corners(g.bbox));
  src.updateImage({ url: bigCanvas.toDataURL() });
}

/* Pins on the ~10 deepest calm pockets — visible at any zoom, click to fly. */
function updatePocketPins(sh, cand, ref) {
  const g = sh.grid;
  cand.sort((a, b) => a[0] - b[0]);
  const picked = [];
  const minD2 = (800 / 25) ** 2;  // pins at least 800 m apart (25 m pixels)
  for (const [ratio, i, j] of cand) {
    if (picked.every((p) => (p.i - i) ** 2 + (p.j - j) ** 2 > minD2)) {
      picked.push({ i, j, ratio });
      if (picked.length >= 10) break;
    }
  }
  const feats = picked.map((p, n) => {
    const lon = g.bbox.lon_min + (p.i + 0.5) / g.nx * (g.bbox.lon_max - g.bbox.lon_min);
    const lat = g.bbox.lat_min + (p.j + 0.5) / g.ny * (g.bbox.lat_max - g.bbox.lat_min);
    return { type: "Feature", id: n,
      properties: { speed: p.ratio * ref, n: n + 1 },
      geometry: { type: "Point", coordinates: [lon, lat] } };
  });
  map.getSource("pocket-pins").setData({ type: "FeatureCollection", features: feats });
  setPinsVisible(true);
}
function setPinsVisible(on) {
  if (mapReady && map.getLayer("pocket-pins"))
    map.setLayoutProperty("pocket-pins", "visibility", on ? "visible" : "none");
}

/* ---------------- particles (screen-space: crisp at every zoom) ----------------
 * Particles are advected in geographic (grid) space but DRAWN on a viewport
 * canvas in screen pixels, so trails stay 1.5 px wide at any zoom. They spawn
 * inside the current viewport, the apparent speed law is constant on screen
 * (px/s proportional to m/s), and trails clear during map interaction.
 */
const pCanvas = document.createElement("canvas");
let particles = [], lastT = 0, regToDet = null, pCtx = null;
function initParticles() {
  pCanvas.id = "particle-overlay";
  $("#mapwrap").appendChild(pCanvas);
  pCtx = pCanvas.getContext("2d");
  sizeParticleCanvas();
  map.on("resize", sizeParticleCanvas);
  // affine region-grid -> detail-grid transform (both linear in lon/lat)
  const R = GRIDS.region, D = GRIDS.detail;
  const sx = (R.bbox.lon_max - R.bbox.lon_min) / R.nx / ((D.bbox.lon_max - D.bbox.lon_min) / D.nx);
  const sy = (R.bbox.lat_max - R.bbox.lat_min) / R.ny / ((D.bbox.lat_max - D.bbox.lat_min) / D.ny);
  const [ox, oy] = lngLatToGrid(D, ...gridToLngLat(R, 0, 0));
  regToDet = (fx, fy) => [ox + fx * sx, oy + fy * sy];
  particles = [];
  requestAnimationFrame(particleStep);
}
function sizeParticleCanvas() {
  const el = map.getContainer();
  const dpr = window.devicePixelRatio || 1;
  pCanvas.width = el.clientWidth * dpr;
  pCanvas.height = el.clientHeight * dpr;
  pCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
function spawnParticle() {
  const R = GRIDS.region;
  const b = map.getBounds();
  const mw = (b.getEast() - b.getWest()) * 0.1, mh = (b.getNorth() - b.getSouth()) * 0.1;
  const lng = Math.min(Math.max(b.getWest() - mw + Math.random() * (b.getEast() - b.getWest() + 2 * mw),
                                R.bbox.lon_min), R.bbox.lon_max);
  const lat = Math.min(Math.max(b.getSouth() - mh + Math.random() * (b.getNorth() - b.getSouth() + 2 * mh),
                                R.bbox.lat_min), R.bbox.lat_max);
  const [x, y] = lngLatToGrid(R, lng, lat);
  return { x: Math.min(Math.max(x, 0), R.nx - 1), y: Math.min(Math.max(y, 0), R.ny - 1),
           age: Math.random() * 2, life: 3 + Math.random() * 6 };
}
function particleTargetCount() {
  const dpr = window.devicePixelRatio || 1;
  const area = (pCanvas.width / dpr) * (pCanvas.height / dpr);
  return Math.max(250, Math.min(1100, Math.round(area / 1600)));
}
function sampleUV(fx, fy) {
  const det = RUN.domains.detail;
  if (det && regToDet) {
    const [dx, dy] = regToDet(fx, fy);
    if (dx >= 0 && dy >= 0 && dx <= GRIDS.detail.nx - 1 && dy <= GRIDS.detail.ny - 1) {
      return [bilin(det.u10, GRIDS.detail, dx, dy), bilin(det.v10, GRIDS.detail, dx, dy)];
    }
  }
  const reg = RUN.domains.region;
  return [bilin(reg.u10, GRIDS.region, fx, fy), bilin(reg.v10, GRIDS.region, fx, fy)];
}
function particleStep(t) {
  requestAnimationFrame(particleStep);
  if (!pCtx) return;
  const dt = Math.min((t - lastT) / 1000 || 0.016, 0.05);
  lastT = t;
  const dpr = window.devicePixelRatio || 1;
  const w = pCanvas.width / dpr, h = pCanvas.height / dpr;
  if (!state.particles || !RUN || !mapReady || document.hidden) {
    if (state._pCleared !== true) { pCtx.clearRect(0, 0, w, h); state._pCleared = true; }
    return;
  }
  if (map.isMoving()) { pCtx.clearRect(0, 0, w, h); return; }
  state._pCleared = false;

  const n = particleTargetCount();
  while (particles.length < n) particles.push(spawnParticle());
  if (particles.length > n) particles.length = n;

  // Constant apparent-speed law: px/s = 4 x wind speed (m/s), at any zoom.
  const c = map.getCenter();
  const p1 = map.project([c.lng, c.lat]);
  const p2 = map.project([c.lng + 5e-4, c.lat]);
  const pxPerM = Math.hypot(p2.x - p1.x, p2.y - p1.y)
               / (5e-4 * 111320 * Math.cos((c.lat * Math.PI) / 180));
  const T = Math.min(4000, Math.max(8, 4.0 / Math.max(pxPerM, 1e-9)));

  pCtx.globalCompositeOperation = "destination-in";
  pCtx.fillStyle = "rgba(0,0,0,0.94)";
  pCtx.fillRect(0, 0, w, h);
  pCtx.globalCompositeOperation = "source-over";
  pCtx.lineWidth = 1.5;
  pCtx.strokeStyle = "rgba(255,255,255,0.85)";
  const R = GRIDS.region, dxm = R.dx_m;
  pCtx.beginPath();
  for (const p of particles) {
    const [u, v] = sampleUV(p.x, p.y);
    const g0 = gridToLngLat(R, p.x, p.y);
    p.x += (u / dxm) * T * dt;
    p.y += (v / dxm) * T * dt;
    p.age += dt;
    if (p.x < 0 || p.x > R.nx - 1 || p.y < 0 || p.y > R.ny - 1 || p.age > p.life) {
      Object.assign(p, spawnParticle());
      continue;
    }
    const s0 = map.project(g0);
    const s1 = map.project(gridToLngLat(R, p.x, p.y));
    if (s1.x < -60 || s1.x > w + 60 || s1.y < -60 || s1.y > h + 60) {
      Object.assign(p, spawnParticle());
      continue;
    }
    pCtx.moveTo(s0.x, s0.y);
    pCtx.lineTo(s1.x, s1.y);
  }
  pCtx.stroke();
}

/* ---------------- suburbs: markers, popup, table ---------------- */
function suburbCoord(name) {
  const s = STATIC.suburbs.find((x) => x.name === name);
  return s ? [s.lon, s.lat] : null;
}
/* Badges describe LIVED exposure, so they key off the windiness score (mean
 * + gusts + turbulence), not mean speed alone — a rotor suburb like Vredehoek
 * has a modest mean but violent gusts and must not read as "Sheltered".
 * A high-turbulence suburb is called out as gusty rather than merely windy. */
function badge(r) {
  const s = r.score, gusty = r.ti_mean >= 0.50;
  if (s >= 55) return { t: gusty ? "Gust-blasted" : "Wind-blasted", c: "#b91c1c" };
  if (s >= 45) return { t: gusty ? "Gusty" : "Exposed", c: "#ea580c" };
  if (s >= 38) return { t: "Part-sheltered", c: "#ca8a04" };
  return { t: "Sheltered", c: "#16a34a" };
}
function effectTags(r) {
  const tags = [];
  if (r.channel_share > 0.15) tags.push(["⏩", "Venturi channeling"]);
  if (r.coanda_share > 0.25) tags.push(["↪️", "Coanda deflection"]);
  if (r.rotor_mean > 0.25) tags.push(["🌀", "lee-rotor gusts"]);
  if ((r.downwash_share || 0) > 0.05) tags.push(["🏙️", "tall-building downwash"]);
  return tags;
}
/* ---------------- weather-station overlay ---------------- */
// A solid up-pointing (north) arrow as an SDF image so icon-color can recolor
// it per station; icon-rotate then aims it downwind.
function makeArrowImage() {
  const s = 30, c = document.createElement("canvas");
  c.width = c.height = s;
  const x = c.getContext("2d"), m = s / 2;
  x.clearRect(0, 0, s, s);
  x.fillStyle = "#000";
  x.beginPath();
  x.moveTo(m, 3); x.lineTo(m + 8, 16); x.lineTo(m + 3.2, 16);
  x.lineTo(m + 3.2, 27); x.lineTo(m - 3.2, 27); x.lineTo(m - 3.2, 16);
  x.lineTo(m - 8, 16); x.closePath(); x.fill();
  return { width: s, height: s, data: new Uint8Array(x.getImageData(0, 0, s, s).data.buffer) };
}
// How closely the observed bearing matches the model bearing here.
function stationMatchColor(err) {
  if (err == null) return "#64748b";
  return err <= 20 ? "#15803d" : err <= 45 ? "#d97706" : "#dc2626";
}
function updateStationSource() {
  if (!mapReady || !map.getSource("stations")) return;
  const vis = showStations ? "visible" : "none";
  ["station-halo", "station-arrows"].forEach((id) =>
    map.getLayer(id) && map.setLayoutProperty(id, "visibility", vis));
  if (!STATIONS) return;
  const lab = SECTOR_LABELS[state.dirIdx];
  const features = [];
  for (const s of STATIONS.stations) {
    const d = s.by_dir[lab];
    if (!d) continue;                       // no data for this input direction
    const hasDir = d.obs_dir != null;
    features.push({
      type: "Feature",
      properties: {
        id: s.id, name: s.name || s.id, n: d.n, hasDir,
        bearing: hasDir ? (d.obs_dir + 180) % 360 : 0,   // downwind, matches the flow particles
        color: stationMatchColor(d.dir_err),
        size: d.obs_speed_p90 || d.obs_speed || 1,
        obs_dir: d.obs_dir, obs_speed: d.obs_speed, obs_p90: d.obs_speed_p90,
        model_dir: d.model_dir, model_speed: d.model_speed, dir_err: d.dir_err,
      },
      geometry: { type: "Point", coordinates: [s.lon, s.lat] },
    });
  }
  map.getSource("stations").setData({ type: "FeatureCollection", features });
}
function openStationPopup(e) {
  const p = e.features[0].properties;
  const lab = SECTOR_LABELS[state.dirIdx];
  const verdict = p.dir_err == null ? "no usable direction here"
    : p.dir_err <= 20 ? "closely matches the model"
    : p.dir_err <= 45 ? "a fair match" : "diverges from the model";
  const dirLine = p.hasDir
    ? `from <b>${Math.round(p.obs_dir)}°</b> · ${fmtSpeed(p.obs_speed, true)} mean (${fmtSpeed(p.obs_p90, true)} p90)`
    : `direction too sparse · ${fmtSpeed(p.obs_speed, true)} mean`;
  if (popup) popup.remove();
  popup = new mapboxgl.Popup({ offset: 12 })
    .setLngLat(e.features[0].geometry.coordinates)
    .setHTML(`<div class="popup-title">${p.name} <span style="opacity:.6">${p.id}</span></div>
      <div class="popup-sub">
        Over <b>${p.n} h</b> of <b>${lab}</b> False-Bay input:<br>
        <b>Observed:</b> ${dirLine}<br>
        <b>Model here:</b> from <b>${Math.round(p.model_dir)}°</b> · ${fmtSpeed(p.model_speed, true)} strong<br>
        ${p.dir_err == null ? "" : `<b>Direction Δ ${Math.round(p.dir_err)}°</b> — ${verdict}.<br>`}
        <span style="opacity:.65">Arrow = observed bearing, colour = direction match. Speeds aren't directly comparable (PWS siting; observed mean vs model strong/p90).</span>
      </div>`)
    .addTo(map);
}

function updateSuburbSource() {
  if (!mapReady || !RUN) return;
  // Marker colour = windiness score (the ranking quantity), so the map and
  // the table tell the same story — windy suburbs are hot, calm ones cool.
  const features = RUN.ranking.map((r) => ({
    type: "Feature",
    id: r.suburb,
    properties: { name: r.suburb, score: r.score, color: scoreColor(r.score) },
    geometry: { type: "Point", coordinates: suburbCoord(r.suburb) },
  }));
  map.getSource("suburbs").setData({ type: "FeatureCollection", features });
}
function openSuburbPopup(name) {
  const r = RUN.ranking.find((x) => x.suburb === name);
  const c = suburbCoord(name);
  if (!r || !c) return;
  const b = badge(r);
  const p = scoreParts(r);
  const tags = effectTags(r);
  const html = `
    <div class="popup-title">${r.suburb}</div>
    <div class="popup-sub">${r.group} · rank #${RUN.rankMap.get(r.suburb)} of ${RUN.ranking.length} · elev ${Math.round(r.elev_m)} m</div>
    <span class="popup-badge" style="background:${b.c}">${b.t}</span>
    <span class="popup-badge" style="background:${scoreColor(r.score)}"
      title="= ${p.mean.toFixed(0)} wind + ${p.gust.toFixed(0)} gusts + ${p.ti.toFixed(0)} turbulence">
      score ${r.score}/100</span>
    <div class="popup-grid">
      <span class="k">Street wind</span><span>${fmtSpeed(r.speed10_mean, true)}</span>
      <span class="k">Gusts</span><span>${fmtSpeed(r.gust_mean, true)}</span>
      <span class="k">Speed-up</span><span>${r.speedup.toFixed(2)}× vs open sea</span>
      <span class="k">Turbulence</span><span>${r.ti_mean.toFixed(2)}</span>
      <span class="k">Flow turned</span><span>${Math.abs(r.deflection_mean).toFixed(0)}°</span>
    </div>
    <div class="popup-tags">Score = ${p.mean.toFixed(0)} (mean wind) + ${p.gust.toFixed(0)} (gusts) + ${p.ti.toFixed(0)} (turbulence)</div>
    ${tags.length ? `<div class="popup-tags">${tags.map(([i, t]) => `${i} ${t}`).join("<br>")}</div>` : ""}`;
  if (popup) popup.remove();
  popup = new mapboxgl.Popup({ offset: 10 }).setLngLat(c).setHTML(html).addTo(map);
}

function renderTable() {
  if (!RUN) return;
  // Reinforce the coupling: the ranking reflects the direction set above.
  $("#rankDirNote").textContent = `· for the ${RUN.meta.dir_label} wind`;
  const tbody = $("#rankTable tbody");
  let rows = [...RUN.ranking];
  if (state.group !== "all") rows = rows.filter((r) => r.group === state.group);
  if (state.search) {
    const q = state.search.toLowerCase();
    rows = rows.filter((r) => r.suburb.toLowerCase().includes(q));
  }
  const { key, asc } = state.sort;
  rows.sort((a, b) => {
    const va = a[key], vb = b[key];
    const cmp = typeof va === "string" ? va.localeCompare(vb) : va - vb;
    return asc ? cmp : -cmp;
  });
  tbody.innerHTML = rows.map((r) => {
    const b = badge(r);
    const tags = effectTags(r).map(([i, t]) => `<span title="${t}">${i}</span>`).join("");
    return `<tr data-name="${r.suburb}">
      <td>${RUN.rankMap.get(r.suburb)}</td>
      <td><div class="sub-name"><span class="b" style="background:${b.c}" title="${b.t}"></span>
        <div><div>${r.suburb} <span class="tags">${tags}</span></div>
        <span class="g">${r.group}</span></div></div></td>
      <td class="num"><span class="score-pill" style="background:${scoreColor(r.score)}">${r.score}</span></td>
      <td class="num">${fmtSpeed(r.speed10_mean)}</td>
      <td class="num">${fmtSpeed(r.gust_mean)}</td>
      <td class="num">${r.ti_mean.toFixed(2)}</td>
    </tr>`;
  }).join("");
  tbody.querySelectorAll("tr").forEach((tr) => {
    const name = tr.dataset.name;
    tr.addEventListener("click", () => {
      map.flyTo({ center: suburbCoord(name), zoom: Math.max(map.getZoom(), 12.8), speed: 1.6 });
      openSuburbPopup(name);
    });
    tr.addEventListener("mouseenter", () => setHover(name));
    tr.addEventListener("mouseleave", () => setHover(null));
  });
  $('#rankTable th[data-sort="speed10_mean"]').textContent = `Wind ${UNITS[state.units].lbl}`;
}
function setHover(name) {
  if (!mapReady) return;
  if (hoverFeatureId) map.setFeatureState({ source: "suburbs", id: hoverFeatureId }, { hover: false });
  hoverFeatureId = name;
  if (name) map.setFeatureState({ source: "suburbs", id: name }, { hover: true });
}

/* ---------------- legend (fixed, pinned on the map) ----------------
 * One layer ⇒ one key. The turbo gradient scales to the scenario inflow; the
 * pin note is static HTML in index.html. */
function renderLegend() {
  const canvas = $("#legendCanvas"), ctx = canvas.getContext("2d");
  for (let x = 0; x < canvas.width; x++) {
    ctx.fillStyle = cmapCss(OVERLAYS.speed10.cmap, x / (canvas.width - 1));
    ctx.fillRect(x, 0, 1, canvas.height);
  }
  const [lo, hi] = overlayRange(), mid = (lo + hi) / 2;
  const f = (v) => fmtSpeed(v) + " " + UNITS[state.units].lbl;
  $("#legendLabels").innerHTML = `<span>${f(lo)}</span><span>${f(mid)}</span><span>${f(hi)}</span>`;
}

/* ---------------- probe ---------------- */
let probeTimer = 0;
function onProbeMove(e) {
  const now = performance.now();
  if (now - probeTimer < 40 || !RUN) return;
  probeTimer = now;
  const probe = $("#probe");
  // prefer the 75 m domain when the cursor is inside it
  let g = GRIDS.detail, run = RUN.domains.detail, [fx, fy] = lngLatToGrid(g, e.lngLat.lng, e.lngLat.lat);
  if (!run || fx < 0 || fy < 0 || fx > g.nx - 1 || fy > g.ny - 1) {
    g = GRIDS.region; run = RUN.domains.region;
    [fx, fy] = lngLatToGrid(g, e.lngLat.lng, e.lngLat.lat);
  }
  if (!run || fx < 0 || fy < 0 || fx > g.nx - 1 || fy > g.ny - 1) { probe.hidden = true; return; }
  const elev = bilin(g.elev, g, fx, fy);
  let micro = "";
  const sh = shelterCache.get(state.dirIdx);
  if (sh && g === GRIDS.detail) {
    const [sx, sy] = lngLatToGrid(sh.grid, e.lngLat.lng, e.lngLat.lat);
    if (sx >= 0 && sy >= 0 && sx <= sh.grid.nx - 1 && sy <= sh.grid.ny - 1) {
      const v = bilin(run.speed10, g, fx, fy) * bilin(sh.factor, sh.grid, sx, sy);
      micro = ` · 25 m ≈ ${fmtSpeed(v, true)}`;
    }
  }
  probe.innerHTML = `⛰ ${Math.round(elev)} m · 💨 ${fmtSpeed(bilin(run.speed10, g, fx, fy), true)} · ` +
    `gust ${fmtSpeed(bilin(run.gust, g, fx, fy), true)} · ${bilin(run.speedup, g, fx, fy).toFixed(2)}× · ` +
    `turb ${bilin(run.ti, g, fx, fy).toFixed(2)}${micro} · ${g === GRIDS.detail ? "75 m" : "200 m"} grid`;
  probe.hidden = false;
}

/* ---------------- scenario chip & URL ---------------- */
function updateChip() {
  const m = RUN.meta;
  const s = STATIC.sectors[state.dirIdx];
  const season = s.summer_share > s.winter_share * 1.4 ? "☀️ summer wind" :
                 s.winter_share > s.summer_share * 1.4 ? "🌧️ winter wind" : "year-round";
  $("#scenarioChip").innerHTML =
    `<b>${m.dir_label}</b> ${Math.round(m.dir_deg)}° · strong (top 10%) · ` +
    `inflow ${fmtSpeed(m.speed_10m, true)} · ${season}` +
    (m.air_note ? ` <span class="muted">· ${m.air_note}</span>` : "") +
    (m.sparse ? ` <span class="warn">· few observed hours</span>` : "");
}
function syncHash() {
  history.replaceState(null, "",
    `#d=${SECTOR_LABELS[state.dirIdx]}&u=${state.units}`);
}
function parseHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  const d = SECTOR_LABELS.indexOf((p.get("d") || "").toUpperCase());
  if (d >= 0) state.dirIdx = d;
  if (UNITS[p.get("u")]) state.units = p.get("u");
}

/* ---------------- orchestration ---------------- */
async function setDirection(k) { state.dirIdx = ((k % 16) + 16) % 16; await refreshRun(); }
async function refreshRun() {
  const seq = ++loadSeq;
  updateRose();
  try {
    const run = await loadRun(state.dirIdx, state.strength);
    if (seq !== loadSeq) return;
    RUN = run;
    renderAll();
  } catch (err) {
    console.error(err);
    $("#scenarioChip").innerHTML = `⚠️ failed to load this wind field`;
  }
}
function renderAll() {
  if (!RUN) return;
  renderField();
  if (mapReady) $("#loading").style.display = "none";
  updateSuburbSource();
  updateStationSource();
  renderTable();
  renderLegend();
  updateChip();
  syncHash();
  if (popup) { popup.remove(); popup = null; }
}
/* Keep the panel "View" 2D/3D switch and the map-corner 3D button showing the
 * same state, whichever surface the user clicked. */
function syncViewButtons() {
  if (viewControl) viewControl._sync();
  document.querySelectorAll("#viewSeg button").forEach((b) =>
    b.classList.toggle("on", (b.dataset.view === "3d") === state.threeD));
}
/* Set 3D on/off to a specific value (the panel switch); toggleThreeD just flips
 * it (the map-corner button), so only call it when the state actually changes. */
function setThreeD(on) {
  if (state.threeD !== on) toggleThreeD();
  syncViewButtons();
}
function updateUnitsSeg() {
  $("#unitsSeg").querySelectorAll("button").forEach((b) =>
    b.classList.toggle("on", b.dataset.unit === state.units));
}
function buildGroupFilters() {
  const wrap = $("#groupFilters");
  wrap.innerHTML = "";
  for (const grp of ["all", ...GROUP_ORDER]) {
    const b = document.createElement("button");
    b.className = "chip small" + (grp === state.group ? " on" : "");
    b.textContent = grp === "all" ? "All" : grp;
    b.addEventListener("click", () => {
      state.group = grp;
      wrap.querySelectorAll(".chip").forEach((x) => x.classList.toggle("on", x === b));
      renderTable();
    });
    wrap.appendChild(b);
  }
}
function wireControls() {
  document.querySelectorAll(".presets .chip").forEach((b) =>
    b.addEventListener("click", async () => {
      state.dirIdx = b.dataset.preset === "se" ? 6 : 14;
      await refreshRun();
    }));
  $("#opacity").addEventListener("input", (e) => {
    state.opacity = e.target.value / 100;
    if (mapReady) {
      // Apply to whichever box layer is active; the inactive one stays at 0.
      const microActive = shelterCache.has(state.dirIdx);
      map.setPaintProperty("field-region", "raster-opacity", state.opacity);
      map.setPaintProperty("field-detail", "raster-opacity", microActive ? 0 : state.opacity);
      map.setPaintProperty("field-pockets", "raster-opacity", microActive ? state.opacity : 0);
    }
  });
  // Settings popover (units + map opacity) — demoted set-once controls.
  $("#settingsBtn").addEventListener("click", (e) => {
    e.stopPropagation();
    $("#settingsPanel").hidden = !$("#settingsPanel").hidden;
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#settingsPanel") && !e.target.closest("#settingsBtn"))
      $("#settingsPanel").hidden = true;
  });
  $("#unitsSeg").querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => {
      state.units = b.dataset.unit;
      updateUnitsSeg();
      updateRose(); renderTable(); renderLegend(); updateChip(); syncHash();
    }));
  // Panel 2D/3D switch mirrors the map-corner 3D button.
  $("#viewSeg").querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => setThreeD(b.dataset.view === "3d")));
  $("#suburbSearch").addEventListener("input", (e) => {
    state.search = e.target.value.trim();
    renderTable();
  });
  $("#rankTable thead").querySelectorAll("th[data-sort]").forEach((th) =>
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (state.sort.key === key) state.sort.asc = !state.sort.asc;
      else state.sort = { key, asc: key === "suburb" };
      document.querySelectorAll("#rankTable th").forEach((x) => x.classList.remove("sorted", "asc"));
      th.classList.add("sorted");
      if (state.sort.asc) th.classList.add("asc");
      renderTable();
    }));
  $("#csvBtn").addEventListener("click", () => {
    if (!RUN) return;
    const cols = Object.keys(RUN.ranking[0]);
    const csv = [cols.join(","), ...RUN.ranking.map((r) => cols.map((c) => r[c]).join(","))].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `ranking_${SECTOR_LABELS[state.dirIdx]}_${state.strength}.csv`;
    a.click();
  });
  $("#scoreInfoBtn").addEventListener("click", (e) => {
    e.stopPropagation();
    $("#scorePopover").hidden = !$("#scorePopover").hidden;
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#scorePopover") && e.target.id !== "scoreInfoBtn")
      $("#scorePopover").hidden = true;
  });
  $("#aboutBtn").addEventListener("click", () => ($("#aboutModal").hidden = false));
  $("#aboutClose").addEventListener("click", () => ($("#aboutModal").hidden = true));
  $("#aboutModal").addEventListener("click", (e) => { if (e.target.id === "aboutModal") e.target.hidden = true; });
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || !$("#aboutModal").hidden) {
      if (e.key === "Escape") $("#aboutModal").hidden = true;
      return;
    }
    if (e.key === "ArrowLeft") setDirection(state.dirIdx - 1);
    if (e.key === "ArrowRight") setDirection(state.dirIdx + 1);
  });
  const ts = $("#toggleStations");
  if (ts) ts.addEventListener("change", () => { showStations = ts.checked; updateStationSource(); });
  $("#opacity").value = Math.round(state.opacity * 100);
  updateUnitsSeg();
}

/* ---------------- boot ---------------- */
async function boot() {
  parseHash();
  try {
    const resp = await fetch(`data/static.json?v=${DATA_VERSION}`);
    if (!resp.ok) throw new Error(`static.json: HTTP ${resp.status} — did you run scripts/precompute_web.py?`);
    STATIC = await resp.json();
    fetch(`data/stations.json?v=${DATA_VERSION}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((s) => { STATIONS = s; updateStationSource(); })
      .catch(() => {});
    GRIDS = {
      region: gridFromStatic(STATIC.domains.region),
      detail: gridFromStatic(STATIC.domains.detail),
    };
    buildRose();
    buildGroupFilters();
    wireControls();
    initMap();
    initParticles();
    syncViewButtons();
    await refreshRun();
    loadShelter(state.dirIdx).catch(() => {});  // warm the pocket layer + probe
  } catch (err) {
    console.error(err);
    $("#loading").innerHTML = `<p>⚠️ ${err.message}</p>`;
  }
}
boot();
