# Raspberry Pi Boot Configuration

To use the CC1101 radio backend and the BME280 environmental sensor, you must enable the hardware SPI and I2C buses on the Raspberry Pi. Both interfaces are disabled by default.

## 1. Enable SPI (For CC1101 Radio and e-Ink Display)
SPI is required for both the Waveshare IT8951 e-ink display HAT and the CC1101 transceiver.

Enable it interactively via the configuration menu:
```bash
sudo raspi-config  →  Interface Options  →  SPI  →  Enable
```

Or, enable it directly by adding this line to `/boot/firmware/config.txt` (or `/boot/config.txt` on older OS versions) and rebooting:
```text
dtparam=spi=on
```

After a reboot, you can verify that the SPI device nodes exist:
```bash
ls /dev/spidev0.*
# Should show: /dev/spidev0.0  /dev/spidev0.1
```

## 2. Enable I2C (For BME280 Sensor)
I2C is required to read temperature, humidity, and pressure data from the local BME280 sensor.

Enable it interactively via the configuration menu:
```bash
sudo raspi-config  →  Interface Options  →  I2C  →  Enable
```

Or, enable it directly by adding this line to `/boot/firmware/config.txt` (or `/boot/config.txt` on older OS versions) and rebooting:
```text
dtparam=i2c_arm=on
```

After a reboot, you can verify that the primary I2C device node exists:
```bash
ls -lah /dev/i2c-1
# Should show a character device owned by root:i2c
```

---
**⚠️ Important Note:** 
If you modify `/boot/firmware/config.txt` manually, a full system reboot is absolutely required before the `/dev/spidev0.*` and `/dev/i2c-1` devices will become available to the Python scripts.
