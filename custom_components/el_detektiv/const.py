"""Constants for the El-detektiv integration."""
from __future__ import annotations

DOMAIN = "el_detektiv"

# Config-entry keys
CONF_TOTAL_POWER = "total_power"          # the whole-home power sensor (W)
CONF_MEASURED_PLUGS = "measured_plugs"    # smart plugs that already report W
CONF_TRACKED_ENTITIES = "tracked_entities"  # on/off entities w/o power meter
CONF_STEP_THRESHOLD = "step_threshold"    # W
CONF_SAMPLE_INTERVAL = "sample_interval"  # seconds
CONF_MIN_DURATION = "min_duration"        # seconds
CONF_MATCH_WINDOW = "match_window"        # seconds, transition<->event coincidence

DEFAULT_STEP_THRESHOLD = 120.0
DEFAULT_SAMPLE_INTERVAL = 10
DEFAULT_MIN_DURATION = 20.0
DEFAULT_MATCH_WINDOW = 90.0

STORAGE_VERSION = 1
STORAGE_KEY = "el_detektiv_signatures"

# Dispatcher / event names
EVENT_DETECTED = "el_detektiv_event_detected"   # fired on HA bus on new unlabeled event
SIGNAL_UPDATE = "el_detektiv_update"

# Services
SERVICE_LABEL_EVENT = "label_event"
SERVICE_CONFIRM_SUGGESTION = "confirm_suggestion"
SERVICE_DISMISS_EVENT = "dismiss_event"
SERVICE_DELETE_SIGNATURE = "delete_signature"
SERVICE_RENAME_SIGNATURE = "rename_signature"
SERVICE_ADD_MANUAL_SIGNATURE = "add_manual_signature"

ATTR_EVENT_ID = "event_id"
ATTR_LABEL = "label"
ATTR_NEW_LABEL = "new_label"
ATTR_WATT = "watt"
ATTR_DURATION = "duration"

MAX_PENDING = 50  # cap the unlabeled-event queue


def is_on_state(state: str | None) -> bool:
    """Generic on/active interpretation across domains."""
    if state is None:
        return False
    return state.lower() in (
        "on", "home", "playing", "open", "heat", "cool", "auto",
        "heat_cool", "active", "cleaning", "running",
    )
