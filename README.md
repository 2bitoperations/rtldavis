# rtldavis

### Purpose
This project aims to implement a receiver for Davis Instruments wireless weather stations by making use of inexpensive rtl-sdr dongles.

[![Build Status](https://travis-ci.org/bemasher/rtldavis.svg?branch=master&style=flat)](https://travis-ci.org/bemasher/rtldavis)
[![GPLv3 License](https://img.shields.io/badge/license-GPLv3-blue.svg?style=flat)](http://choosealicense.com/licenses/gpl-3.0/)

### Requirements
 * Python >=3.12
 * uv (https://github.com/astral-sh/uv)
 * rtl-sdr: [github.com/steve-m/librtlsdr](https://github.com/steve-m/librtlsdr)

### Building
The following instructions assume that you have already built and installed the rtl-sdr tools and library above. Please see build instructions provided here: [http://sdr.osmocom.org/trac/wiki/rtl-sdr#Buildingthesoftware](http://sdr.osmocom.org/trac/wiki/rtl-sdr#Buildingthesoftware)

To build the project, the following commands will install dependencies and prepare the project for execution:

	uv sync --all-extras

### Testing
To run the tests, navigate to the project directory and use the `pytest` command:

	uv run pytest

### Usage
Available command-line flags are as follows:

```
usage: rtldavis [-h] [-v] [--version] [--list-rtlsdr-devices]
                [--rtlsdr-device RTLSDR_DEVICE]
                [--station-id STATION_ID] [--ppm PPM] [--gain GAIN] [--no-hop]
                [--mqtt-broker MQTT_BROKER] [--mqtt-port MQTT_PORT]
                [--mqtt-discovery-prefix MQTT_DISCOVERY_PREFIX]
                [--mqtt-state-prefix MQTT_STATE_PREFIX]
                [--mqtt-client-id MQTT_CLIENT_ID]
                [--mqtt-username MQTT_USERNAME] [--mqtt-password MQTT_PASSWORD]

Davis Instruments weather station receiver using RTL-SDR

options:
  -h, --help            show this help message and exit
  -v, --verbose         Increase logging verbosity
  --version             Show version and exit
  --list-rtlsdr-devices
                        List detected RTL-SDR devices
  --rtlsdr-device RTLSDR_DEVICE
                        Select RTL-SDR device by serial number or index
  --station-id STATION_ID
                        Davis station ID to filter for (0-7)
  --ppm PPM             Frequency correction in PPM
  --gain GAIN           Tuner gain. Can be 'auto' or a value in tenths of a dB
                        (e.g., 49.6).
  --no-hop              Disable frequency hopping for debugging
  --mqtt-broker MQTT_BROKER
                        MQTT broker hostname
  --mqtt-port MQTT_PORT
                        MQTT broker port
  --mqtt-discovery-prefix MQTT_DISCOVERY_PREFIX
                        MQTT discovery topic prefix
  --mqtt-state-prefix MQTT_STATE_PREFIX
                        MQTT topic prefix for sensor state
  --mqtt-client-id MQTT_CLIENT_ID
                        MQTT client ID
  --mqtt-username MQTT_USERNAME
                        MQTT username
  --mqtt-password MQTT_PASSWORD
                        MQTT password
  --http-port HTTP_PORT
                        Port for the REST API server (GET /sensors). Default: 8088.
```

### REST API

The application exposes a read-only HTTP endpoint that returns the latest value received for every sensor.

**Endpoint:** `GET /sensors`

**Default port:** `8088` (configurable via `--http-port`)

**Response:** a JSON object where each key is a sensor identifier. Example:

```json
{
  "wind_speed": {
    "name": "wind_speed",
    "description": "Wind Speed",
    "value": 14.5,
    "timestamp_ms": 1711497600123,
    "units": "km/h"
  },
  "wind_direction": {
    "name": "wind_direction",
    "description": "Wind Direction",
    "value": 270,
    "timestamp_ms": 1711497600123,
    "units": "°"
  },
  "temperature": {
    "name": "temperature",
    "description": "Temperature",
    "value": 68.4,
    "timestamp_ms": 1711497600456,
    "units": "°F"
  }
}
```

Each entry contains:

| Field | Description |
|---|---|
| `name` | Sensor identifier (same as the key) |
| `description` | Human-readable sensor name |
| `value` | Latest received value |
| `timestamp_ms` | Unix timestamp of the reading in milliseconds |
| `units` | Unit of measurement, or `null` if not applicable |

The response only includes sensors for which at least one reading has been received since startup. No authentication is required.

Known sensor keys include: `wind_speed`, `wind_direction`, `wind_gust_speed`, `temperature`, `humidity`, `rain_total_raw`, `rain_total_hourly`, `rain_total_daily`, `rain_total_weekly`, `rain_rate`, `uv_index`, `solar_radiation`, `light`, `supercap_voltage`, `rssi`, `snr`.

### Raspberry Pi OS Installation (Bookworm/Trixie)

This project can be installed as a systemd service on Raspberry Pi OS Bookworm and Trixie.

**1. Run the Installer:**

Execute the installer script as root:

```bash
sudo ./install.sh
```

**2. Configure the Service:**

Edit the configuration file to match your setup:

```bash
sudo nano /etc/default/rtldavis
```

**3. Start and Manage the Service:**

-   **Start:** `sudo systemctl start rtldavis`
-   **Stop:** `sudo systemctl stop rtldavis`
-   **Restart:** `sudo systemctl restart rtldavis`
-   **Check Status:** `sudo systemctl status rtldavis`

**4. View Logs:**

Logs are sent to the systemd journal.

-   **View all logs:** `journalctl -u rtldavis`
-   **Tail logs in real-time:** `journalctl -u rtldavis -f`

### RTL-SDR Blog V4 on Older Systems

If you are using an RTL-SDR Blog V4 dongle on an older system (like Raspberry Pi OS Bookworm), you may need to update your `librtlsdr` library to a newer version. The version provided by the OS may not be compatible with the V4 dongle.

To update your `librtlsdr` library, run the following script as root:

```bash
sudo ./install_librtlsdr.sh
```

After the script completes, reboot your system for the changes to take effect.

### License
The source of this project is licensed under GPL v3.0. According to [http://choosealicense.com/licenses/gpl-3.0/](http://choosealicense.com/licenses/gpl-3.0/) you may:

#### Required:

 * **Disclose Source:** Source code must be made available when distributing the software. In the case of LGPL and OSL 3.0, the source for the library (and not the entire program) must be made available.
 * **License and copyright notice:** Include a copy of the license and copyright notice with the code.
 * **State Changes:** Indicate significant changes made to the code.

#### Permitted:

 * **Commercial Use:** This software and derivatives may be used for commercial purposes.
 * **Distribution:** You may distribute this software.
 * **Modification:** This software may be modified.
 * **Patent Use:** This license provides an express grant of patent rights from the contributor to the recipient.
 * **Private Use:** You may use and modify the software without distributing it.

#### Forbidden:

 * **Hold Liable:** Software is provided without warranty and the software author\/license owner cannot be held liable for damages.

### Feedback
If you have any general questions or feedback leave a comment below. For bugs, feature suggestions and anything directly relating to the program itself, submit an issue.
