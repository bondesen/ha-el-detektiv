# El-detektiv 🔌🕵️

Non-intrusive load identification (NILM-light) for Home Assistant. Find out
**what is actually drawing your power** — without putting a smart plug on
everything.

El-detektiv watches your whole-home power meter, subtracts the loads you
*can* measure (smart plugs), and learns the rest from the steps your total
consumption makes when things switch on and off:

- **Auto-learning** for on/off entities you already have in HA (gaming PC,
  NAS, TV, …). When the device flips on and the total jumps at the same
  moment, El-detektiv records that device's wattage signature — and refines
  it every time.
- **Human-in-the-loop** for appliances that aren't in HA at all (kettle,
  iron, vacuum). When it sees an unexplained excursion it can't match, it
  queues it: *"From 19:12 to 19:25 there was a ~2000 W spike that matches
  nothing — what were you doing?"* You answer once ("boiled water"), and a
  new candidate signature is born. Next time it suggests the label itself;
  you confirm, and its confidence grows.
- **Tolerant matching.** Signatures are stored as running mean **and spread**
  (plus typical duration and time-of-day), so appliances that never draw
  exactly the same twice still match.

Everything runs 24/7 inside Home Assistant and survives restarts (signatures
are persisted). A companion sidebar dashboard (built separately) reads these
entities and drives the labelling.

## Entities

| Entity | What it is |
|---|---|
| `sensor.el_detektiv_uforklaret_effekt` | Live "dark" load: total − measured plugs − known active signatures (W) |
| `sensor.el_detektiv_signaturer` | Count of learned appliances; `library` attribute holds the full signature table |
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

## How detection works

Each sample interval the integration computes `residual = total − measured plugs`
and feeds it to an edge detector. A sustained rise above the rolling baseline
opens an event; the return to baseline closes it, yielding `(Δwatt, duration)`.
If a tracked entity switched on within the match window, the event is
attributed to it automatically; otherwise it is queued for you to label.
Signature statistics use Welford's online algorithm so mean and variance
update in O(1) per sample.

## Configuration tips

- **Step threshold** (default 120 W): raise it if your baseline is noisy and
  you get too many tiny events; lower it to catch smaller appliances.
- **Tracked entities**: add anything with a clear on/off (or playing/idle)
  state. Network-presence `device_tracker`s work but are noisier than real
  power states.

---

Built for a specific Danish smart home, but generic. MIT licensed.
