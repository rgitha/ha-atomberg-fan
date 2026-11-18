# Atomberg Fan

Local Bluetooth control of Atomberg smart ceiling fans in Home Assistant. No cloud account
and no Wi-Fi setup needed: the fan is controlled through a Bluetooth adapter on the Home
Assistant host or an ESPHome Bluetooth proxy.

## Supported fans

- **Renesa (R1)**: tested.
- Other fans that advertise as `Atomberg_<series>_<id>` may work but aren't tested. Their
  diagnostics download helps add them.

## What you get

| Entity | Does |
|---|---|
| Fan | On and off, speeds 1 to 5, and the **Boost** preset |
| LED | The fan's speed LEDs on or off |
| Sleep mode | Sleep mode on or off |
| Timer | Off after 1, 2, 3 or 6 hours |

Diagnostic:

| Entity | Does |
|---|---|
| Identify | Blinks the speed LEDs, to find which fan this is |
| Update status | Reads the fan now |
| Updated last | When the fan last reported its state |
| Signal strength | Signal strength of the fan's Bluetooth |
| Connection link | Whether the Bluetooth link is open (**Active** or **Idle**). Disabled by default |
| Motor speed, Voltage, Current, Board temperature, Runtime, Restarts, Wi-Fi configured | Extra details the fan reports. Their meanings are best guesses, not yet confirmed |

## Installation

### HACS
1. In HACS, open the menu and choose **Custom repositories**.
2. Add `https://github.com/rgitha/ha-atomberg-fan` as an **Integration**.
3. Install **Atomberg Fan** and restart Home Assistant.

### Manual
Copy `custom_components/atomberg_fan` into your `config/custom_components` folder and
restart Home Assistant.

## Setup

Fans in range are found automatically and offered under **Settings → Devices & services**.
Or choose **Add integration → Atomberg Fan** and pick a fan, or enter its Bluetooth address.

Then choose how it connects:

- **Set up: connect when needed** connects only to send a command or check the fan. Changes
  made with the remote show within about a minute.
- **Set up: stay connected** shows changes made with the remote at once, but uses one
  Bluetooth connection slot all the time (most proxies have three).

Not sure which fan is which? Choose **Blink its LEDs**: its speed LEDs blink a few times, then
go back to how they were.

## Options

**Stay connected** can be changed any time under **Configure**.

## How updates work

The fan is read about once a minute while it's in range.

When connecting when needed, Home Assistant connects for each command and for each read, and
drops the link a few seconds later. So a change made with the remote shows within about a
minute.

When staying connected, every change shows at once, and the link is reopened when the fan is
heard after it drops. The fan is still read once a minute, for its extra details.

## Known limitations

- Bluetooth only. Wi-Fi control isn't possible without the vendor's cloud on the fans
  tested so far.
- No brightness or colour control on the Renesa: its LED is on or off.
- A phone connected to the fan over Bluetooth can block Home Assistant from connecting.

## Removal

Delete the fan under **Settings → Devices & services → Atomberg Fan**, then remove the
integration in HACS.

## Disclaimer

Not affiliated with or endorsed by Atomberg Technologies. Use at your own risk.
