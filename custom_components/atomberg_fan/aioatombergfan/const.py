"""Atomberg BLE protocol constants (verified on an R1 / Renesa fan).

See PROTOCOL.md for the reverse-engineering notes behind these values.
"""

from __future__ import annotations

# --- GATT ---
SERVICE_UUID = "9256cc8a-85b3-46a6-a4a4-9b6a2e1248be"
CMD_CHAR = "e29ee02c-af3d-11ec-b909-0242ac120002"  # write JSON cmd; notify/read 4-byte state
STATE_CHAR = "9fa1610e-e6fc-11ec-8fea-0242ac120002"  # read full comma-separated state string
APLIST_CHAR = "36684e6a-df79-4e4b-b031-0620ecf10cae"  # read scanned Wi-Fi AP list
WIFI_CHAR = "f1bd396f-8a7a-43a9-a112-777eb60db2aa"  # write {"ssid","pswd"} (provisioning)
WIFI_STATUS_CHAR = "9d1619e6-7130-4aec-a63e-f1ab2bb55fbd"  # read Wi-Fi status byte

# --- advertisement ---
NAME_PREFIX = "Atomberg_"  # local name: Atomberg_<SERIES>_<device_id>

# --- speed ---
MIN_SPEED = 1
MAX_SPEED = 6  # 6 == boost on the R1

# --- byte-0 state bit flags (also field 0 of the state string) ---
MASK_SPEED = 0x07
BIT_POWER = 0x10
BIT_LED = 0x20
BIT_BOOST = 0x40  # always set together with speed 6
BIT_SLEEP = 0x80

# --- timer: command value -> hours (state byte 2 reads the hours) ---
TIMER_VALUE_TO_HOURS = {0: 0, 1: 1, 2: 2, 3: 3, 4: 6}
TIMER_HOURS_TO_VALUE = {0: 0, 1: 1, 2: 2, 3: 3, 6: 4}

# Wi-Fi status byte (read from WIFI_STATUS_CHAR); raw value is offset by one
# from the app's display codes.
WIFI_STATUS = {
    0: "connected",
    1: "network_not_found",
    2: "wrong_password",
    3: "no_internet",
    4: "cloud_unreachable",
}
