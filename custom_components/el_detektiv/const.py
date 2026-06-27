"""Constants for the El-detektiv integration."""
from __future__ import annotations

DOMAIN = "el_detektiv"

# Config-entry keys
CONF_TOTAL_POWER = "total_power"          # the whole-home power sensor (W)
CONF_MEASURED_PLUGS = "measured_plugs"    # smart plugs that already report W
CONF_TRACKED_ENTITIES = "tracked_entities"  # on/off entities w/o power meter
CONF_STEP_THRESHOLD = "step_threshold"    # W (whole-home NILM)
CONF_SAMPLE_INTERVAL = "sample_interval"  # seconds
CONF_MIN_DURATION = "min_duration"        # seconds
CONF_MATCH_WINDOW = "match_window"        # seconds, transition<->event coincidence

# Test meter (supervised learning) + lower threshold
CONF_TEST_METER = "test_meter"                  # dedicated plug you move around
CONF_TEST_STEP_THRESHOLD = "test_step_threshold"  # W (isolated, can be low)

# Notifications (optional — leave empty for dashboard-only)
CONF_NOTIFY_SERVICE = "notify_service"      # any notify.* service, e.g. notify.telegram
CONF_TELEGRAM_CHAT_ID = "telegram_chat_id"  # set -> interactive Telegram buttons

DEFAULT_STEP_THRESHOLD = 120.0
DEFAULT_SAMPLE_INTERVAL = 10
DEFAULT_MIN_DURATION = 20.0
DEFAULT_MATCH_WINDOW = 90.0
DEFAULT_TEST_STEP_THRESHOLD = 20.0

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
SERVICE_START_TEST_SESSION = "start_test_session"
SERVICE_STOP_TEST_SESSION = "stop_test_session"

ATTR_EVENT_ID = "event_id"
ATTR_LABEL = "label"
ATTR_NEW_LABEL = "new_label"
ATTR_WATT = "watt"
ATTR_DURATION = "duration"

MAX_PENDING = 50  # cap the unlabeled-event queue

# A signature at this confidence is trusted enough to auto-attribute silently
# (no notification) and to auto-finish a test session.
CONFIDENCE_TRUSTED = "hoej"


def is_on_state(state: str | None) -> bool:
    """Generic on/active interpretation across domains."""
    if state is None:
        return False
    return state.lower() in (
        "on", "home", "playing", "open", "heat", "cool", "auto",
        "heat_cool", "active", "cleaning", "running",
    )
