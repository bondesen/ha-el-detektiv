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
- **Human-in-the-loop** for appliances that aren't in HA at all (kettle,
  iron, vacuum): an unexplained excursion is queued/notified — *"~2000 W,
  matches nothing — what were you doing?"* — and you label it once.
- **Test sessions (supervised learning).** Plug a device into a dedicated
  **test meter**, start a session with the device's name, and El-detektiv
  learns its profile from the *clean, isolated* measurement until it's
  confident — then recognises it anywhere on the house, even moved to a dumb
  wall socket. See [Test sessions](#test-sessions-supervised-learning).
- **Configurable notifications.** Get an interactive **Telegram** message when
  a new profile turns up and label it with one tap (or a typed name) — or use
  any `notify.*` service, or nothing at all (dashboard-only). See
  [Notifications](#notifications).
- **Conservative attribution & confidence gate.** A coincident device
  state-change is only trusted when its signature matches; and once a device
  is **well learned (high confidence)** its events are auto-counted *silently*
  — you stop being pinged for things it already knows.
- **Tolerant matching** (running mean + spread + duration + time-of-day) and
  **per-device energy** (kWh per device over an adjustable period).

Everything runs 24/7 inside Home Assistant and survives restarts.

## Test sessions (supervised learning)

The most reliable way to teach El-detektiv an appliance it can't see:

1. Designate a **test meter** in the integration options (any power sensor —
   typically a smart plug you move around). Tip: also add it to
   *measured plugs* so its draw is subtracted from the whole-home residual.
2. Plug the appliance into the test meter **switched off**, then call
   `el_detektiv.start_test_session` with `label: "Elkedel"` (or use the card).
3. Use the appliance normally for a while (a few on/off cycles, e.g. over a
   couple of days). Each cycle is measured directly on the test meter and
   added to that label's signature — down to a low `test_step_threshold`
   (default **20 W**), because the measurement is isolated and clean.
4. When the signature reaches **high confidence** the session **ends itself**
   and you're notified. Move the appliance to any normal socket — the
   whole-home detector now matches the same wattage step to the learned label.

> A device that's *on the whole time* won't produce on/off cycles to learn
> from; toggle it a few times, or seed it with `add_manual_signature`.

## Notifications

Configured in the integration options — pick what suits you:

- **Telegram (interactive).** Set `telegram_chat_id` (and have the
  `telegram_bot` integration running). New unexplained events arrive with
  inline buttons: **the suggested name**, **✏️ Nyt navn** (reply with a typed
  name), and **🗑 Ignorér**. Tapping a name (or replying) creates the signature
  with count 1 / increments it if it exists.
- **Any notify service.** Set `notify_service` to e.g. `notify.mobile_app_x`
  for a plain-text heads-up; label from the dashboard.
- **Dashboard-only.** Leave both blank — events just appear in the card.

Notifications **stop automatically** for a device once it reaches high
confidence (it's then auto-counted silently).

## The card

A dependency-free custom card (`custom:el-detektiv-card`) is bundled and
auto-registered. Add it to any dashboard:

```yaml
type: custom:el-detektiv-card
```

It shows snapshot tiles, a stacked composition chart, device on/off lanes,
the labelling queue, and the signature library with a kWh column and period
selector.

## Entities

| Entity | What it is |
|---|---|
| `sensor.el_detektiv_uforklaret_effekt` | Live "dark" load (W); attributes expose `total_power` / `measured_plugs` / `tracked` and the active `test_label`. |
| `sensor.el_detektiv_signaturer` | Count of learned appliances; `library` attribute holds the signature table incl. per-run energy log. |
| `sensor.el_detektiv_ulabelede_haendelser` | Count of unlabeled events; `events` attribute holds the queue with suggestions. |

A `el_detektiv_event_detected` event fires on the HA bus for every new
unexplained excursion.

## Services

- `el_detektiv.label_event` — name an unexplained event → create/refine a signature
- `el_detektiv.confirm_suggestion` — accept the suggested label
- `el_detektiv.dismiss_event` — drop a noise event
- `el_detektiv.start_test_session` / `el_detektiv.stop_test_session` — supervised learning via the test meter
- `el_detektiv.add_manual_signature` — seed a signature you already know
- `el_detektiv.rename_signature` / `el_detektiv.delete_signature`

## Installation (HACS)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/bondesen/ha-el-detektiv`, category **Integration**.
2. Install **El-detektiv**, then restart Home Assistant.
3. Settings → Devices & Services → **Add Integration** → *El-detektiv*.
4. Pick total power sensor, measured plugs, tracked on/off entities, and
   (optionally) a **test meter** + **notify service / Telegram chat id**.
5. Add `type: custom:el-detektiv-card` to a dashboard (hard-refresh once).

## How detection works

Each sample interval the integration computes `residual = total − measured plugs`
and feeds it to an edge detector. A sustained rise above the rolling baseline
opens an event; the return to baseline closes it, yielding `(Δwatt, duration)`.
Matching, attribution, and the confidence gate then decide whether to count it
silently, queue/notify it, or learn it. Signature statistics use Welford's
online algorithm.

**Baseline robustness.** The idle baseline is seeded from a *median of the
first several samples* and re-syncs if an event stays open far longer than any
real transient — so a stray low reading at startup can't pin the baseline
below the real floor and leave the detector blind. Covered by
`tests/test_nilm_core.py` (`pytest tests/`, no HA needed).

## Configuration tips

- **Step threshold** (default 120 W): the whole-home NILM threshold. The
  house baseline is noisy (±tens of W), so going very low here yields many
  false events.
- **Test step threshold** (default 20 W): used only on the isolated test
  meter, where a much lower threshold is reliable.
- **Match window** (default 90 s): how close a tracked device's state-change
  must be to an event to be considered the cause.

## Changelog

### 0.7.0
- **Test sessions** (`start_test_session` / `stop_test_session`): supervised
  learning of an appliance from a dedicated **test meter**, with a separate
  low `test_step_threshold` (default 20 W); auto-finishes at high confidence.
- **Configurable notifications**: interactive Telegram (inline buttons +
  reply-to-name), any `notify.*` service, or dashboard-only.
- **Confidence gate**: events matching a high-confidence signature are
  auto-counted silently (no more notifications for known devices).

### 0.6.1
- **Fix — baseline self-heal.** A low power reading at startup could pin the
  idle baseline below the real floor, leaving the detector "in an event" and
  blind (kettles undetected until a reload). Baseline now warms up from a
  median and re-syncs if stuck. Added `tests/test_nilm_core.py`.

---

MIT licensed. Built for a specific Danish smart home, but generic.
