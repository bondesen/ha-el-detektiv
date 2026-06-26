/*! El-detektiv card — native Lovelace, dependency-free. Per-device energy + period. */
const VERSION = "0.5.0";

const DEF = {
  unexplained: "sensor.el_detektiv_uforklaret_effekt",
  signatures: "sensor.el_detektiv_signaturer",
  pending: "sensor.el_detektiv_ulabelede_haendelser",
  total_power: null, measured_plugs: null, tracked: null, hours: 24,
};

const ON_STATES = ["on", "home", "playing", "open", "heat", "cool", "auto", "heat_cool", "active", "cleaning", "running"];
const isOn = s => !!s && ON_STATES.includes(String(s).toLowerCase());

const PERIODS = [["today", "I dag"], ["week", "Denne uge"], ["month", "Denne måned"], ["year", "I år"], ["30d", "Seneste 30 dage"], ["all", "Alt"]];
function periodStart(key) {
  const n = new Date();
  if (key === "today") { n.setHours(0, 0, 0, 0); return n.getTime() / 1000; }
  if (key === "week") { const d = n.getDay() || 7; n.setHours(0, 0, 0, 0); n.setDate(n.getDate() - (d - 1)); return n.getTime() / 1000; }
  if (key === "month") return new Date(n.getFullYear(), n.getMonth(), 1).getTime() / 1000;
  if (key === "year") return new Date(n.getFullYear(), 0, 1).getTime() / 1000;
  if (key === "30d") return (Date.now() - 30 * 86400000) / 1000;
  return 0;
}

const CSS = `
:host{ --fridge:#2563eb; --plugs:#0d9488; --amber:#f59e0b; --ok:#16a34a; --ink:var(--primary-text-color); }
ha-card{ padding:14px 16px 16px; }
.h{ display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; margin-bottom:10px; }
.h .t{ font-size:1.15em; font-weight:600; }
.h .v{ margin-left:auto; font-size:1.7em; font-weight:700; line-height:1; }
.h .u{ font-size:.5em; font-weight:400; color:var(--secondary-text-color); }
.tiles{ display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:8px; margin-bottom:14px; }
.tile{ border:1px solid var(--divider-color); border-radius:10px; padding:8px 10px; }
.tile .k{ font-size:.7em; text-transform:uppercase; letter-spacing:.04em; color:var(--secondary-text-color); display:flex; align-items:center; gap:5px; }
.tile .sw{ width:9px; height:9px; border-radius:2px; display:inline-block; }
.tile .val{ font-size:1.25em; font-weight:650; margin-top:2px; }
.legend{ display:flex; gap:14px; flex-wrap:wrap; font-size:.78em; color:var(--secondary-text-color); margin-bottom:4px; }
.legend span{ display:inline-flex; align-items:center; gap:5px; }
.sw{ width:11px; height:11px; border-radius:3px; display:inline-block; }
.chart{ width:100%; height:150px; display:block; }
.lanes{ margin-top:4px; }
.lane{ display:flex; align-items:center; height:20px; }
.lane .lbl{ width:88px; min-width:88px; font-size:.7em; color:var(--secondary-text-color); text-align:right; padding-right:8px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.lane .track{ position:relative; flex:1; height:11px; background:var(--divider-color); border-radius:3px; overflow:hidden; opacity:.85; }
.seg{ position:absolute; top:0; height:11px; border-radius:2px; }
.axis{ display:flex; justify-content:space-between; font-size:.62em; color:var(--secondary-text-color); padding-left:88px; margin-top:2px; }
.sec{ font-size:.78em; text-transform:uppercase; letter-spacing:.04em; color:var(--secondary-text-color); margin:16px 0 6px; font-weight:600; }
.sechead{ display:flex; align-items:center; justify-content:space-between; gap:8px; margin:16px 0 6px; }
.sechead .sec{ margin:0; }
.sechead select{ font:inherit; font-size:.85em; padding:3px 6px; border-radius:7px; border:1px solid var(--divider-color); background:var(--card-background-color); color:var(--ink); }
.sigtotal{ text-align:right; font-size:.85em; color:var(--secondary-text-color); margin-top:6px; }
.sigtotal b{ color:var(--ink); }
.empty{ color:var(--secondary-text-color); font-style:italic; padding:6px 0; }
.ev{ border:1px solid var(--divider-color); border-radius:10px; padding:10px; margin-bottom:8px; }
.ev .top{ display:flex; align-items:baseline; gap:8px; flex-wrap:wrap; }
.ev .w{ font-weight:700; font-size:1.05em; color:var(--amber); }
.ev .meta{ color:var(--secondary-text-color); font-size:.85em; }
.ev .sug{ margin-left:auto; font-size:.85em; }
.row{ display:flex; gap:6px; margin-top:8px; flex-wrap:wrap; }
.row input{ flex:1; min-width:120px; padding:6px 8px; border-radius:8px; border:1px solid var(--divider-color); background:var(--card-background-color); color:var(--ink); font:inherit; }
button{ font:inherit; border:1px solid var(--divider-color); background:var(--card-background-color); color:var(--ink); padding:6px 10px; border-radius:8px; cursor:pointer; }
button.primary{ background:var(--primary-color); color:var(--text-primary-color,#fff); border-color:transparent; }
button.ok{ background:var(--ok); color:#fff; border-color:transparent; }
button.ghost{ color:var(--secondary-text-color); }
table{ width:100%; border-collapse:collapse; font-size:.92em; }
th,td{ text-align:left; padding:6px 6px; border-bottom:1px solid var(--divider-color); }
th{ font-size:.72em; text-transform:uppercase; letter-spacing:.03em; color:var(--secondary-text-color); }
td.num{ text-align:right; font-variant-numeric:tabular-nums; }
.pill{ display:inline-block; font-size:.72em; padding:1px 8px; border-radius:20px; }
.pill.hoej{ background:rgba(22,163,74,.16); color:var(--ok); }
.pill.middel{ background:rgba(245,158,11,.18); color:var(--amber); }
.pill.lav{ background:var(--divider-color); color:var(--secondary-text-color); }
.bar{ height:6px; border-radius:4px; background:var(--amber); opacity:.7; }
.foot{ color:var(--secondary-text-color); font-size:.72em; margin-top:4px; }
`;

class ElDetektivCard extends HTMLElement {
  setConfig(config) { this._config = { ...DEF, ...(config || {}) }; }
  getCardSize() { return 12; }
  static getStubConfig() { return {}; }

  set hass(hass) { this._hass = hass; if (!this._built) this._build(); this._update(); }

  _resolve() {
    const c = this._config;
    const a = ((this._st(c.unexplained) || {}).attributes) || {};
    return {
      total_power: c.total_power || a.total_power || null,
      measured_plugs: c.measured_plugs || a.measured_plugs || [],
      tracked: c.tracked || a.tracked || [],
    };
  }

  _build() {
    this._built = true;
    this._inputs = {}; this._lastPending = null; this._lastSigs = null; this._graphAt = 0;
    this.attachShadow({ mode: "open" });
    const style = document.createElement("style"); style.textContent = CSS;
    const card = document.createElement("ha-card");
    card.innerHTML = `
      <div class="h"><span class="t">🔌 El-detektiv</span>
        <span class="v" id="val">–<span class="u"> W uforklaret</span></span></div>
      <div class="tiles" id="tiles"></div>
      <div class="legend" id="legend"></div>
      <svg class="chart" id="chart" preserveAspectRatio="none"></svg>
      <div class="lanes" id="lanes"></div>
      <div class="axis" id="axis"></div>
      <div class="foot" id="foot"></div>
      <div class="sec">Ulabelede hændelser</div>
      <div id="pending"></div>
      <div class="sechead">
        <span class="sec">Lærte signaturer</span>
        <select id="period" title="Forbrugsperiode">${PERIODS.map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select>
      </div>
      <div id="sigs"></div>`;
    this.shadowRoot.append(style, card);
    const sel = this.shadowRoot.getElementById("period");
    let saved = "month";
    try { saved = localStorage.getItem("el_detektiv_period") || "month"; } catch (e) {}
    sel.value = saved;
    sel.addEventListener("change", () => {
      try { localStorage.setItem("el_detektiv_period", sel.value); } catch (e) {}
      this._renderSigs(this._sigLib || []);
    });
  }

  _st(id) { return id && this._hass && this._hass.states[id]; }
  _num(id) { const s = this._st(id); const v = s ? parseFloat(s.state) : NaN; return isNaN(v) ? 0 : v; }
  _name(id) { const s = this._st(id); return (s && s.attributes && s.attributes.friendly_name) || id; }

  _update() {
    const c = this._config;
    const r = this._r = this._resolve();
    const plugs = r.measured_plugs;
    const total = r.total_power ? this._num(r.total_power) : 0;
    const fridge = plugs.length ? this._num(plugs[0]) : 0;
    let other = 0; for (let i = 1; i < plugs.length; i++) other += this._num(plugs[i]);
    const phantom = Math.max(0, total - fridge - other);
    const fridgeName = plugs.length ? this._name(plugs[0]) : "Største stik";

    const u = this._st(c.unexplained);
    const valEl = this.shadowRoot.getElementById("val");
    if (u) valEl.innerHTML = `${Math.round(parseFloat(u.state) || 0)}<span class="u"> W uforklaret</span>`;

    const W = x => (x >= 1000 ? (x / 1000).toFixed(2) + " kW" : Math.round(x) + " W");
    const tiles = [];
    if (r.total_power) tiles.push(["Total nu", W(total), null]);
    if (plugs.length) tiles.push([fridgeName, W(fridge), "var(--fridge)"]);
    if (plugs.length > 1) tiles.push(["Øvrige stik", W(other), "var(--plugs)"]);
    tiles.push(["Umålt (phantom)", r.total_power ? W(phantom) : (u ? W(parseFloat(u.state) || 0) : "–"), "var(--amber)"]);
    this.shadowRoot.getElementById("tiles").innerHTML = tiles.map(([k, v, col]) =>
      `<div class="tile"><div class="k">${col ? `<i class="sw" style="background:${col}"></i>` : ""}${k}</div><div class="val">${v}</div></div>`).join("");

    this.shadowRoot.getElementById("legend").innerHTML = r.total_power && plugs.length ? `
      <span><i class="sw" style="background:var(--fridge)"></i>${fridgeName}</span>
      <span><i class="sw" style="background:var(--plugs)"></i>Øvrige målte stik</span>
      <span><i class="sw" style="background:var(--amber)"></i>Umålt (phantom)</span>` : "";
    this.shadowRoot.getElementById("foot").textContent = r.total_power && plugs.length
      ? "Stablede arealer summer til totalforbruget. Bjælker = enhed tændt/spillede." : "";

    const pend = this._st(c.pending);
    const events = (pend && pend.attributes.events) || [];
    const pk = JSON.stringify(events);
    if (pk !== this._lastPending) { this._lastPending = pk; this._renderPending(events); }

    const sg = this._st(c.signatures);
    const lib = (sg && sg.attributes.library) || [];
    this._sigLib = lib;
    const sk = JSON.stringify(lib);
    if (sk !== this._lastSigs) { this._lastSigs = sk; this._renderSigs(lib); }

    if (Date.now() - this._graphAt > 5 * 60 * 1000) { this._graphAt = Date.now(); this._loadGraph(); }
  }

  async _loadGraph() {
    const r = this._r || this._resolve();
    if (!r.total_power || !r.measured_plugs.length) { this._clearGraph(); return; }
    const startISO = new Date(Date.now() - this._config.hours * 3600 * 1000).toISOString();
    try {
      const ids = [r.total_power, ...r.measured_plugs];
      const stats = await this._hass.callWS({ type: "recorder/statistics_during_period", start_time: startISO, statistic_ids: ids, period: "5minute" });
      const getStart = it => (typeof it.start === "number" ? it.start : Date.parse(it.start));
      const totArr = (stats && stats[r.total_power]) || [];
      if (totArr.length < 2) { this._clearGraph(); return; }
      const plugMaps = r.measured_plugs.map(p => { const m = {}; ((stats && stats[p]) || []).forEach(it => { m[getStart(it)] = it.mean; }); return m; });
      const rows = totArr.map(it => {
        const t = getStart(it), tot = it.mean;
        const fr = plugMaps[0][t] || 0;
        let oth = 0; for (let i = 1; i < plugMaps.length; i++) oth += plugMaps[i][t] || 0;
        return { t, fridge: fr, other: oth, phantom: Math.max(0, tot - fr - oth), total: tot };
      });
      const t0 = rows[0].t, t1 = rows[rows.length - 1].t;
      this._drawComposition(rows, t0, t1);
      await this._drawLanes(r.tracked, t0, t1, startISO);
      this._drawAxis(t0, t1);
    } catch (e) { this._clearGraph(); }
  }

  _clearGraph() { ["chart", "lanes", "axis"].forEach(id => { const el = this.shadowRoot.getElementById(id); if (el) el.innerHTML = ""; }); }

  _drawComposition(rows, t0, t1) {
    const svg = this.shadowRoot.getElementById("chart");
    const W = 800, H = 150, pad = 4;
    const span = (t1 - t0) || 1;
    const maxY = Math.max(...rows.map(r => r.total)) * 1.1 || 1;
    const x = t => pad + (t - t0) / span * (W - 2 * pad);
    const y = v => H - pad - (v / maxY) * (H - 2 * pad);
    const band = (lo, hi) => {
      let top = "", bot = "";
      rows.forEach((r, i) => { top += `${i ? "L" : "M"}${x(r.t).toFixed(1)} ${y(hi(r)).toFixed(1)} `; });
      for (let i = rows.length - 1; i >= 0; i--) { bot += `L${x(rows[i].t).toFixed(1)} ${y(lo(rows[i])).toFixed(1)} `; }
      return top + bot + "Z";
    };
    const f = r => r.fridge, o = r => r.fridge + r.other, p = r => r.fridge + r.other + r.phantom;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.innerHTML =
      `<path d="${band(() => 0, f)}" fill="var(--fridge)" fill-opacity="0.55"/>` +
      `<path d="${band(f, o)}" fill="var(--plugs)" fill-opacity="0.55"/>` +
      `<path d="${band(o, p)}" fill="var(--amber)" fill-opacity="0.55"/>` +
      `<path d="${rows.map((r, i) => `${i ? "L" : "M"}${x(r.t).toFixed(1)} ${y(r.total).toFixed(1)}`).join(" ")}" fill="none" stroke="var(--primary-text-color)" stroke-opacity="0.5" stroke-width="1"/>`;
  }

  async _drawLanes(tracked, t0, t1, startISO) {
    const box = this.shadowRoot.getElementById("lanes"); box.innerHTML = "";
    if (!tracked || !tracked.length) return;
    let hist;
    try { hist = await this._hass.callApi("GET", `history/period/${startISO}?filter_entity_id=${tracked.join(",")}&minimal_response&significant_changes_only`); } catch (e) { return; }
    const span = (t1 - t0) || 1;
    const byId = {};
    (hist || []).forEach(arr => { if (arr && arr.length) byId[arr[0].entity_id] = arr; });
    for (const eid of tracked) {
      const arr = byId[eid] || [];
      const states = arr.map(s => ({ t: Date.parse(s.last_changed || s.last_updated), on: isOn(s.state) })).filter(s => !isNaN(s.t)).sort((a, b) => a.t - b.t);
      const segs = []; let cur = null; let startOn = false;
      for (const s of states) { if (s.t <= t0) startOn = s.on; }
      if (startOn) cur = t0;
      for (const s of states) {
        if (s.t < t0) continue;
        if (s.on && cur === null) cur = s.t;
        else if (!s.on && cur !== null) { segs.push([cur, s.t]); cur = null; }
      }
      if (cur !== null) segs.push([cur, t1]);
      const bars = segs.map(([a, b]) => {
        const l = (Math.max(a, t0) - t0) / span * 100, w = Math.max(0.4, (Math.min(b, t1) - Math.max(a, t0)) / span * 100);
        return `<div class="seg" style="left:${l}%;width:${w}%;background:var(--primary-color)"></div>`;
      }).join("");
      const nm = this._name(eid).replace(/ is_home$/, "").replace(/_is_present$/, "");
      box.insertAdjacentHTML("beforeend", `<div class="lane"${segs.length ? "" : ' style="opacity:.45"'}><div class="lbl" title="${nm}">${nm}</div><div class="track">${bars}</div></div>`);
    }
  }

  _drawAxis(t0, t1) {
    const box = this.shadowRoot.getElementById("axis"); box.innerHTML = "";
    const fmt = t => new Date(t).toLocaleTimeString("da-DK", { hour: "2-digit", minute: "2-digit" });
    for (let i = 0; i <= 4; i++) { const t = t0 + (t1 - t0) * i / 4; box.insertAdjacentHTML("beforeend", `<span>${fmt(t)}</span>`); }
  }

  _renderPending(events) {
    const box = this.shadowRoot.getElementById("pending");
    if (!events.length) { box.innerHTML = `<div class="empty">Ingen — alt forklaret lige nu. 👌</div>`; return; }
    box.innerHTML = "";
    for (const ev of events) {
      const t0 = new Date(ev.t_start * 1000), t1 = new Date(ev.t_end * 1000);
      const hhmm = d => d.toLocaleTimeString("da-DK", { hour: "2-digit", minute: "2-digit" });
      const mins = (ev.duration_s / 60).toFixed(ev.duration_s < 600 ? 1 : 0);
      const sug = ev.suggestion ? `<span class="sug">forslag: <b>${ev.suggestion}</b> (${Math.round((ev.suggestion_score || 0) * 100)}%)</span>` : "";
      const el = document.createElement("div"); el.className = "ev";
      el.innerHTML = `
        <div class="top"><span class="w">+${Math.round(ev.delta_w)} W</span><span class="meta">${hhmm(t0)}–${hhmm(t1)} · ${mins} min</span>${sug}</div>
        <div class="row">
          <input type="text" placeholder="Hvad lavede du? (fx Elkedel)" />
          <button class="primary" data-act="label">Gem</button>
          ${ev.suggestion ? `<button class="ok" data-act="confirm">Bekræft ${ev.suggestion}</button>` : ""}
          <button class="ghost" data-act="dismiss">Afvis</button>
        </div>`;
      const input = el.querySelector("input");
      input.value = this._inputs[ev.id] || "";
      input.addEventListener("input", e => { this._inputs[ev.id] = e.target.value; });
      input.addEventListener("keydown", e => { if (e.key === "Enter") this._label(ev.id); });
      el.querySelector('[data-act="label"]').addEventListener("click", () => this._label(ev.id));
      const cf = el.querySelector('[data-act="confirm"]');
      if (cf) cf.addEventListener("click", () => this._svc("confirm_suggestion", { event_id: ev.id }));
      el.querySelector('[data-act="dismiss"]').addEventListener("click", () => this._svc("dismiss_event", { event_id: ev.id }));
      box.appendChild(el);
    }
  }

  _label(id) {
    const label = (this._inputs[id] || "").trim();
    if (!label) return;
    delete this._inputs[id];
    this._svc("label_event", { event_id: id, label });
  }

  _svc(service, data) { if (this._hass) this._hass.callService("el_detektiv", service, data); }

  _renderSigs(lib) {
    const box = this.shadowRoot.getElementById("sigs");
    if (!lib.length) { box.innerHTML = `<div class="empty">Endnu ingen — labelér hændelser, så bygger biblioteket sig op.</div>`; return; }
    const sel = this.shadowRoot.getElementById("period");
    const pkey = (sel && sel.value) || "month";
    const start = periodStart(pkey);
    const kwh = r => (r.runs || []).reduce((s, run) => (run[0] >= start ? s + (run[1] || 0) : s), 0) / 1000;
    const rows = [...lib].sort((a, b) => (b.mean || 0) - (a.mean || 0));
    const maxMean = Math.max(1, ...rows.map(r => r.mean || 0));
    const name = r => (r.label || "").replace(/^sensor\.|^switch\.|^media_player\.|^binary_sensor\.|^device_tracker\.|^climate\./, "");
    let totalKwh = 0; rows.forEach(r => { totalKwh += kwh(r); });
    box.innerHTML = `<table>
      <thead><tr><th>Enhed</th><th class="num">Effekt</th><th class="num">Forbrug</th><th class="num">Målinger</th><th>Tillid</th><th></th></tr></thead>
      <tbody>${rows.map(r => `
        <tr>
          <td>${name(r)}</td>
          <td class="num">${Math.round(r.mean)} W <span style="color:var(--secondary-text-color)">±${Math.round(r.std)}</span></td>
          <td class="num">${kwh(r).toFixed(2)} kWh</td>
          <td class="num">${r.n}</td>
          <td><span class="pill ${r.confidence || "lav"}">${({ hoej: "Høj", middel: "Middel", lav: "Lav" })[r.confidence] || "Lav"}</span></td>
          <td style="width:80px"><div class="bar" style="width:${Math.max(6, (r.mean / maxMean) * 100)}%"></div></td>
        </tr>`).join("")}</tbody></table>
      <div class="sigtotal">Forklaret forbrug i perioden: <b>${totalKwh.toFixed(2)} kWh</b></div>`;
  }
}

if (!customElements.get("el-detektiv-card")) {
  customElements.define("el-detektiv-card", ElDetektivCard);
  window.customCards = window.customCards || [];
  window.customCards.push({ type: "el-detektiv-card", name: "El-detektiv", description: "NILM load identification with stacked composition chart, energy and labelling.", preview: false });
  console.info(`%c EL-DETEKTIV-CARD %c v${VERSION} `, "background:#f59e0b;color:#000;border-radius:3px 0 0 3px;padding:2px 4px", "background:#333;color:#fff;border-radius:0 3px 3px 0;padding:2px 4px");
}
