/*! El-detektiv card — native Lovelace card, dependency-free.
 *  Reads the el_detektiv.* sensors via hass and drives labelling via services.
 *  ships with the El-detektiv integration and auto-registers as a frontend module.
 */
const VERSION = "0.2.0";

const DEF = {
  unexplained: "sensor.el_detektiv_uforklaret_effekt",
  signatures: "sensor.el_detektiv_signaturer",
  pending: "sensor.el_detektiv_ulabelede_haendelser",
  history_hours: 24,
};

const CSS = `
:host{ --amber:#f59e0b; --ok:#16a34a; }
ha-card{ padding:14px 16px 16px; }
.h{ display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; margin-bottom:6px; }
.h .t{ font-size:1.15em; font-weight:600; }
.h .v{ margin-left:auto; font-size:1.8em; font-weight:700; line-height:1; }
.h .u{ font-size:.5em; font-weight:400; color:var(--secondary-text-color); }
.sub{ color:var(--secondary-text-color); font-size:.85em; margin-bottom:10px; }
.chart{ width:100%; height:90px; display:block; margin:4px 0 14px; }
.sec{ font-size:.78em; text-transform:uppercase; letter-spacing:.04em; color:var(--secondary-text-color);
      margin:14px 0 6px; font-weight:600; }
.empty{ color:var(--secondary-text-color); font-style:italic; padding:6px 0; }
.ev{ border:1px solid var(--divider-color); border-radius:10px; padding:10px; margin-bottom:8px; }
.ev .top{ display:flex; align-items:baseline; gap:8px; flex-wrap:wrap; }
.ev .w{ font-weight:700; font-size:1.05em; color:var(--amber); }
.ev .meta{ color:var(--secondary-text-color); font-size:.85em; }
.ev .sug{ margin-left:auto; font-size:.85em; }
.row{ display:flex; gap:6px; margin-top:8px; flex-wrap:wrap; }
.row input{ flex:1; min-width:120px; padding:6px 8px; border-radius:8px;
            border:1px solid var(--divider-color); background:var(--card-background-color);
            color:var(--primary-text-color); font:inherit; }
button{ font:inherit; border:1px solid var(--divider-color); background:var(--card-background-color);
        color:var(--primary-text-color); padding:6px 10px; border-radius:8px; cursor:pointer; }
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
`;

class ElDetektivCard extends HTMLElement {
  setConfig(config) {
    this._config = { ...DEF, ...(config || {}) };
  }
  getCardSize() { return 8; }
  static getConfigElement() { return null; }
  static getStubConfig() { return {}; }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    this._update();
  }

  _build() {
    this._built = true;
    this._inputs = {};
    this._lastPending = null;
    this._lastSigs = null;
    this._histAt = 0;
    this.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = CSS;
    const card = document.createElement("ha-card");
    card.innerHTML = `
      <div class="h"><span class="t">🔌 El-detektiv</span>
        <span class="v" id="val">–<span class="u"> W uforklaret</span></span></div>
      <div class="sub" id="sub"></div>
      <svg class="chart" id="chart" preserveAspectRatio="none"></svg>
      <div class="sec">Ulabelede hændelser</div>
      <div id="pending"></div>
      <div class="sec">Lærte signaturer</div>
      <div id="sigs"></div>`;
    this.shadowRoot.append(style, card);
  }

  _st(id) { return this._hass && this._hass.states[id]; }

  _update() {
    const u = this._st(this._config.unexplained);
    const valEl = this.shadowRoot.getElementById("val");
    const subEl = this.shadowRoot.getElementById("sub");
    if (u) {
      valEl.innerHTML = `${Math.round(parseFloat(u.state) || 0)}<span class="u"> W uforklaret</span>`;
      const base = u.attributes.baseline;
      subEl.textContent = base != null
        ? `Baseline ~${Math.round(base)} W · det jeg endnu ikke kan tilskrive en kendt enhed`
        : "";
    }
    const pend = this._st(this._config.pending);
    const events = (pend && pend.attributes.events) || [];
    const pk = JSON.stringify(events);
    if (pk !== this._lastPending) { this._lastPending = pk; this._renderPending(events); }

    const sg = this._st(this._config.signatures);
    const lib = (sg && sg.attributes.library) || [];
    const sk = JSON.stringify(lib);
    if (sk !== this._lastSigs) { this._lastSigs = sk; this._renderSigs(lib); }

    if (Date.now() - this._histAt > 5 * 60 * 1000) { this._histAt = Date.now(); this._drawChart(); }
  }

  // ---------- pending events (labelling) ----------
  _renderPending(events) {
    const box = this.shadowRoot.getElementById("pending");
    if (!events.length) { box.innerHTML = `<div class="empty">Ingen — alt forklaret lige nu. 👌</div>`; return; }
    box.innerHTML = "";
    for (const ev of events) {
      const t0 = new Date(ev.t_start * 1000), t1 = new Date(ev.t_end * 1000);
      const hhmm = d => d.toLocaleTimeString("da-DK", { hour: "2-digit", minute: "2-digit" });
      const mins = (ev.duration_s / 60).toFixed(ev.duration_s < 600 ? 1 : 0);
      const sug = ev.suggestion
        ? `<span class="sug">forslag: <b>${ev.suggestion}</b> (${Math.round((ev.suggestion_score || 0) * 100)}%)</span>` : "";
      const el = document.createElement("div");
      el.className = "ev";
      el.innerHTML = `
        <div class="top">
          <span class="w">+${Math.round(ev.delta_w)} W</span>
          <span class="meta">${hhmm(t0)}–${hhmm(t1)} · ${mins} min</span>
          ${sug}
        </div>
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

  _svc(service, data) {
    if (this._hass) this._hass.callService("el_detektiv", service, data);
  }

  // ---------- signature library ----------
  _renderSigs(lib) {
    const box = this.shadowRoot.getElementById("sigs");
    if (!lib.length) {
      box.innerHTML = `<div class="empty">Endnu ingen — labelér hændelser, så bygger biblioteket sig op.</div>`;
      return;
    }
    const rows = [...lib].sort((a, b) => (b.mean || 0) - (a.mean || 0));
    const maxMean = Math.max(1, ...rows.map(r => r.mean || 0));
    const name = r => (r.label || "").replace(/^sensor\.|^switch\.|^media_player\.|^binary_sensor\.|^device_tracker\.|^climate\./, "");
    box.innerHTML = `<table>
      <thead><tr><th>Enhed</th><th class="num">Effekt</th><th class="num">Målinger</th><th>Tillid</th><th></th></tr></thead>
      <tbody>${rows.map(r => `
        <tr>
          <td>${name(r)}</td>
          <td class="num">${Math.round(r.mean)} W <span style="color:var(--secondary-text-color)">±${Math.round(r.std)}</span></td>
          <td class="num">${r.n}</td>
          <td><span class="pill ${r.confidence || "lav"}">${({ hoej: "Høj", middel: "Middel", lav: "Lav" })[r.confidence] || "Lav"}</span></td>
          <td style="width:90px"><div class="bar" style="width:${Math.max(6, (r.mean / maxMean) * 100)}%"></div></td>
        </tr>`).join("")}</tbody></table>`;
  }

  // ---------- trend chart (SVG, no deps) ----------
  async _drawChart() {
    const svg = this.shadowRoot.getElementById("chart");
    if (!svg || !this._hass) return;
    try {
      const start = new Date(Date.now() - this._config.history_hours * 3600 * 1000).toISOString();
      const eid = this._config.unexplained;
      const res = await this._hass.callApi(
        "GET", `history/period/${start}?filter_entity_id=${eid}&minimal_response&significant_changes_only`);
      const series = (res && res[0]) || [];
      const pts = series.map(s => ({ t: Date.parse(s.last_changed || s.last_updated), v: parseFloat(s.state) }))
        .filter(p => !isNaN(p.t) && !isNaN(p.v));
      if (pts.length < 2) { svg.innerHTML = ""; return; }
      const W = 600, H = 90, pad = 4;
      const t0 = pts[0].t, t1 = pts[pts.length - 1].t || t0 + 1;
      const vmax = Math.max(...pts.map(p => p.v)) * 1.1 || 1;
      const x = t => pad + (t - t0) / (t1 - t0 || 1) * (W - 2 * pad);
      const y = v => H - pad - (v / vmax) * (H - 2 * pad);
      let d = "", area = "";
      pts.forEach((p, i) => { const X = x(p.t).toFixed(1), Y = y(p.v).toFixed(1); d += `${i ? "L" : "M"}${X} ${Y} `; });
      area = `M${x(pts[0].t).toFixed(1)} ${H - pad} ` + d.replace(/^M/, "L") + `L${x(t1).toFixed(1)} ${H - pad} Z`;
      svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
      svg.innerHTML =
        `<path d="${area}" fill="var(--amber)" fill-opacity="0.15"/>` +
        `<path d="${d}" fill="none" stroke="var(--amber)" stroke-width="1.6"/>`;
    } catch (e) { /* history not available — hide chart silently */ svg.innerHTML = ""; }
  }
}

if (!customElements.get("el-detektiv-card")) {
  customElements.define("el-detektiv-card", ElDetektivCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "el-detektiv-card",
    name: "El-detektiv",
    description: "NILM load identification — label unknown power draws and learn appliance signatures.",
    preview: false,
  });
  console.info(`%c EL-DETEKTIV-CARD %c v${VERSION} `, "background:#f59e0b;color:#000;border-radius:3px 0 0 3px;padding:2px 4px", "background:#333;color:#fff;border-radius:0 3px 3px 0;padding:2px 4px");
}
