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
- **Test sessions (supervised learning)** — the way you teach El-detektiv an
  appliance it can't see. Plug a device into a dedicated
  **test meter**, start a session **right in the card** with the device's
  name, and El-detektiv learns its profile from the *clean, isolated*
  measurement until it's confident — then recognises it anywhere on the house,
  even moved to a dumb wall socket. See
  [Test sessions](#test-sessions-supervised-learning).
- **Silent whole-home matching.** Detected steps are matched against what is
  already known — a coincident tracked device whose signature fits, or a
  high-confidence learned signature — and counted. **Anything it cannot
  attribute is discarded.** No labelling queue, no "what were you doing?"
  notifications.
- **Optional status notifications.** Telegram or any `notify.*` service, used
  only to tell you a test session finished. See [Notifications](#notifications).
- **Tolerant matching** (running mean + spread + duration + time-of-day) and
  **per-device energy** (kWh per device over an adjustable period).

Everything runs 24/7 inside Home Assistant and survives restarts.

## Test sessions (supervised learning)

The most reliable way to teach El-detektiv an appliance it can't see:

1. Designate a **test meter** in the integration options (any power sensor —
   typically a smart plug you move around). El-detektiv **automatically
   subtracts whatever is on the test meter** from the whole-home "unexplained"
   figure, so the thing you're testing never *also* shows up as a house event
   — you do **not** need to add it to *measured plugs*.
2. Plug the appliance into the test meter **switched off**, then in the card's
   **Test-session** panel type a name (e.g. `Elkedel`) and press **Start**.
3. Use the appliance normally for a while (a few on/off cycles, e.g. over a
   couple of days). Each cycle is measured directly on the test meter and
   added to that label's signature — down to a low `test_step_threshold`
   (default **20 W**; set it lower, e.g. **5 W**, for tiny loads like a phone
   charger), because the measurement is isolated and clean.
4. When the signature reaches **high confidence** the session **ends itself**
   and you're notified. Move the appliance to any normal socket — the
   whole-home detector now matches the same wattage step to the learned label
   and counts its runs silently.

**Where:** the card shows a **Test-session** panel — type a name → **Start**,
and **Stop** while it's running (with the live test-meter watt). Prefer
automation? The same thing is exposed as the `el_detektiv.start_test_session`
/ `stop_test_session` services. The active session name is on
`sensor.el_detektiv_uforklaret_effekt` (`test_label` attribute).

> A device that's *on the whole time* won't produce on/off cycles to learn
> from; toggle it a few times, or seed it with `add_manual_signature`.

## Notifications

El-detektiv **never notifies about unexplained power**. The only message it
sends is a status line when a test session finishes ("✅ har lært *X*").
Configured in the integration options:

- **Telegram.** Set `telegram_chat_id` (and have the `telegram_bot`
  integration running).
- **Any notify service.** Set `notify_service` to e.g. `notify.mobile_app_x`.
  Ignored when a Telegram chat id is set.
- **Silent.** Leave both blank.

## The card

A dependency-free custom card (`custom:el-detektiv-card`) is bundled and
auto-registered. Add it to any dashboard:

```yaml
type: custom:el-detektiv-card
```

It shows snapshot tiles, a stacked composition chart, device on/off lanes, a
**test-session panel** (start/stop supervised learning), and the signature
library with a kWh column and period selector.

## Entities

| Entity | What it is |
|---|---|
| `sensor.el_detektiv_uforklaret_effekt` | Live "dark" load (W); attributes expose `total_power` / `measured_plugs` / `tracked` / `test_meter` and the active `test_label`. |
| `sensor.el_detektiv_signaturer` | Count of learned appliances; `library` attribute holds the signature table incl. per-run energy log. |

## Services

- `el_detektiv.start_test_session` / `el_detektiv.stop_test_session` — supervised learning via the test meter (also in the card)
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

Each sample interval the integration computes `residual = total − measured
plugs − test meter` and feeds it to an edge detector. A sustained rise above
the rolling baseline opens an event; the return to baseline closes it, yielding
`(Δwatt, duration)`. The step is then counted against a coincident tracked
device whose signature fits, or against a high-confidence learned signature —
and dropped if neither applies. Signature statistics use Welford's online
algorithm.

**Baseline robustness.** The idle baseline is seeded from a *median of the
first several samples* and re-syncs if an event stays open far longer than any
real transient — so a stray low reading at startup can't pin the baseline
below the real floor and leave the detector blind. Covered by
`tests/test_nilm_core.py` (`pytest tests/`, no HA needed).

## Configuration tips

- **Step threshold** (default 120 W): the whole-home NILM threshold. The
  house baseline is noisy (±tens of W), so going very low here yields many
  false events — ~150 W is a good balance for most homes.
- **Test step threshold** (default 20 W): used only on the isolated test
  meter, where a much lower threshold is reliable (drop to ~5 W for chargers).
- **Match window** (default 90 s): how close a tracked device's state-change
  must be to an event to be considered the cause.

## Changelog

### 0.8.0
- **Removed the unlabeled-event workflow.** No pending queue, no
  `sensor.el_detektiv_ulabelede_haendelser`, no labelling UI in the card, no
  event notifications, no interactive Telegram buttons, and no
  `el_detektiv_event_detected` bus event. Removed services: `label_event`,
  `confirm_suggestion`, `dismiss_event`.
- Whole-home detection still runs, but **silently**: a step is only used to
  count a run on an already-known device; unattributable steps are discarded.
- Learning is now exclusively **test sessions** + `add_manual_signature`.
- Notification config is kept, used only for test-session status.
- Any legacy pending queue in `.storage` is discarded on first save.

### 0.7.2
- **Test sessions are now controlled from the card** — a Test-session panel
  (name → Start, Stop while running, live test-meter watt). Services still work
  for automations.

### 0.7.1
- The **test meter is auto-subtracted** from the whole-home residual — no need
  to also list it under *measured plugs*.

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
