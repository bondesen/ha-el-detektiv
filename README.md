# El-detektiv 🔌🕵️

Non-intrusive load identification (NILM-light) for Home Assistant. Find out
**what is actually drawing your power** — and **how much energy each thing
uses** — without putting a smart plug on everything.

El-detektiv watches your whole-home power meter, subtracts the loads you
*can* measure (smart plugs), and learns the rest from the steps your total
consumption makes when things switch on and off. It ships with a polished
Lovelace card that registers itself — **one HACS install gives you both the
brains and the UI**.

## What it does

- **Auto-learning** for on/off entities already in HA (gaming PC, NAS, TV…).
  When a device flips on and the total jumps at the same moment, El-detektiv
  records that device's wattage signature — and refines it every time.
- **Human-in-the-loop** for appliances that aren't in HA at all (kettle,
  iron, vacuum). An unexplained excursion is queued: *"19:12–19:25, ~2000 W,
  matches nothing — what were you doing?"* You answer once, a candidate
  signature is born, and next time it suggests the label itself.
- **Conservative attribution.** A coincident device state-change is only
  trusted when that device already has a *matching* signature — so a TV going
  to "playing" near a 2 kW kettle spike is queued for confirmation, never
  silently mislabelled.
- **Tolerant matching.** Signatures store running mean **and spread** (plus
  typical duration and time-of-day), so variable appliances still match.
- **Per-device energy.** Every run is logged with a timestamp, so the card
  shows **kWh per device over an adjustable period** (today / week / month /
  year / last 30 days / all).

Everything runs 24/7 inside Home Assistant and survives restarts (signatures
are persisted via the HA Store).

## The card

A dependency-free custom card (`custom:el-detektiv-card`) is bundled with the
integration and auto-registered as a frontend module — no manual resource.
Add it to any dashboard:

```yaml
type: custom:el-detektiv-card
```

It self-configures by reading the entity lists from the integration's
sensor attributes (override per-card with `total_power`, `measured_plugs`,
`tracked`, `hours` if you like). It shows: snapshot tiles, a **stacked
composition chart** (first plug / other plugs / unexplained = total), **device
on/off lanes**, the **labelling queue**, and the **signature library with a
kWh column and period selector**.

## Entities

| Entity | What it is |
|---|---|
| `sensor.el_detektiv_uforklaret_effekt` | Live "dark" load: total − measured plugs − known active signatures (W). Attributes also expose the configured `total_power` / `measured_plugs` / `tracked` so the card can self-configure. |
| `sensor.el_detektiv_signaturer` | Count of learned appliances; `library` attribute holds the signature table incl. per-run energy log |
| `sensor.el_detektiv_ulabelede_haendelser` | Count of unlabeled events; `events` attribute holds the queue with suggestions |

A `el_detektiv_event_detected` event fires on the HA bus for every new
unexplained excursion — hook it to a mobile notification so you can label
while you still remember what you were doing.

## Services

- `el_detektiv.label_event` — name an unexplained event → create/refine a signature
- `el_detektiv.confirm_suggestion` — accept the suggested label (raises confidence)
- `el_detektiv.dismiss_event` — drop a noise event
- `el_detektiv.add_manual_signature` — seed a signature you already know
- `el_detektiv.rename_signature` / `el_detektiv.delete_signature`

## Installation (HACS)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/bondesen/ha-el-detektiv`, category **Integration**.
2. Install **El-detektiv**, then restart Home Assistant.
3. Settings → Devices & Services → **Add Integration** → *El-detektiv*.
4. Pick your total power sensor, your measured plugs, and the on/off entities to track.
5. Add `type: custom:el-detektiv-card` to a dashboard (hard-refresh the browser once so the bundled card loads).

## How detection works

Each sample interval the integration computes `residual = total − measured plugs`
and feeds it to an edge detector. A sustained rise above the rolling baseline
opens an event; the return to baseline closes it, yielding `(Δwatt, duration)`,
and the run's energy `Δwatt × duration` is logged. If a tracked entity with a
matching signature switched on within the match window, the event is attributed
automatically; otherwise it is queued for you to label. Signature statistics
use Welford's online algorithm so mean and variance update in O(1) per sample.

**Baseline robustness.** The idle baseline is seeded from a *median of the
first several samples* (never a single reading), and any event that stays open
far longer than a real transient (`rebaseline_after`, default 30 min) is
abandoned and the baseline re-synced to the current level. This prevents a
stray low reading at startup/reload from pinning the baseline below the real
floor — which would otherwise make the steady floor look like a permanent "on"
and leave the detector blind to new steps until a reload. Covered by
`tests/test_nilm_core.py` (`pytest tests/`, no HA needed).

## Configuration tips

- **Step threshold** (default 120 W): raise it if your baseline is noisy and
  you get too many tiny events; lower it to catch smaller appliances.
- **Match window** (default 90 s): how close a tracked device's state-change
  must be to an event to be considered the cause.
- **Tracked entities**: add anything with a clear on/off (or playing/idle)
  state. Network-presence `device_tracker`s work but are noisier than real
  power states.

> Note: the per-device kWh is the energy of the *runs El-detektiv explained*
> for that appliance — not your household total (your meter already has that).

## Changelog

### 0.6.1
- **Fix — baseline self-heal.** A low power reading at startup (common just
  after a reload) could pin the idle baseline far below the real floor. The
  steady floor then read as a permanent "on", so the detector opened an event
  that never closed and stopped seeing new steps — e.g. kettles went
  undetected until the integration was reloaded. The baseline is now seeded
  from a median of the first samples, and a stuck-open event re-syncs the
  baseline after `rebaseline_after`. Added `tests/test_nilm_core.py`.

---

MIT licensed. Built for a specific Danish smart home, but generic.
