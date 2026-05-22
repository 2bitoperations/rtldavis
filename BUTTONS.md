# 5-Way Switch Integration

This document outlines the hardware wiring and software dependencies required to run the `rtldavis` local UI extensions (the 5-way joystick switch and WebSocket streaming server).

## Hardware Wiring

A standard 5-way tactile switch (Up, Down, Left, Right, Click) requires 5 GPIO inputs and 1 common ground. 

We map these to a contiguous block of odd-numbered physical pins on the Raspberry Pi header. This specific location was chosen because it does not collide with the `SPI0` bus (used by the CC1101 and e-ink HAT) or the `I2C1` bus (used by the BME280).

It allows for easy wiring with a single **1x6 female Dupont connector**:

| Switch Pin | Pi Physical Pin | BCM GPIO |
| :--- | :--- | :--- |
| **Click** | Pin 29 | GPIO 5 |
| **Right** | Pin 31 | GPIO 6 |
| **Left**  | Pin 33 | GPIO 13 |
| **Down**  | Pin 35 | GPIO 19 |
| **Up**    | Pin 37 | GPIO 26 |
| **Common**| Pin 39 | GND |

**Electrical Note:** The driver code configures these GPIOs with internal pull-up resistors. When a button is pressed, the switch pulls the corresponding GPIO line to GND, triggering the interrupt.

## System Dependencies

Because the Raspberry Pi OS (Debian 12 Bookworm) replaced the legacy `sysfs` GPIO interface with `libgpiod`, the Python ecosystem requires the `lgpio` C-extension to interact with the hardware securely.

If you are using a modern Python version (like 3.13) inside a virtual environment (like `uv`), there are no pre-compiled binaries for the GPIO wrappers, so they must be built from source.

You **must** install these OS-level build dependencies before the Python environment will successfully compile the GPIO drivers:

```bash
sudo apt-get update
sudo apt-get install -y swig liblgpio-dev
```

## Running the Application

To start `rtldavis` with the GPIO buttons enabled, pass the `--buttons` flag. This will automatically start the WebSocket streaming server on port `8089`.

```bash
# Example: Running the full stack (Radio + BME280 + Buttons + WebSockets)
uv run rtldavis --radio cc1101 --cc1101-spi-device 1 --bme280 --buttons
```

Once running, the application will emit JSON events to all connected WebSocket clients (`ws://[PI_IP]:8089`) every time a button is pressed or released, formatted like this:

```json
{
  "type": "button",
  "payload": {
    "action": "press",
    "button": "up"
  }
}
```
