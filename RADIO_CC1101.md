# CC1101 Radio Backend

This document describes the plan and design for adding a CC1101 transceiver as an
alternative radio backend to the existing RTL-SDR path.

```
claude --resume 63a60af7-ef9f-4b56-8dee-6660a6f96e0a
```

## Background

The existing RTL-SDR path captures raw I/Q samples at 268,800 Hz and runs a full
software DSP pipeline:

```
RTL-SDR I/Q bytes
  → complex LUT
  → Fs/4 rotation
  → 9-tap FIR filter
  → FSK discriminator
  → quantize to bits
  → preamble search (pattern "1100101110001001")
  → packet slice (80 symbols = 10 bytes)
  → CRC-16-CCITT check
  → protocol.parse()
```

The CC1101 performs all of that in hardware and delivers decoded bytes over SPI.
The two paths merge at the `dsp.Packet` level — everything from `protocol.parse()`
onward is shared.

## CC1101 Register Configuration

| Parameter          | Value          | Reason                                               |
|--------------------|----------------|------------------------------------------------------|
| Sync word          | `0xCB89`       | Davis preamble `1100101110001001` as two bytes        |
| Packet length      | 8 bytes fixed  | 64-symbol payload after the preamble                 |
| Hardware CRC       | Off            | Davis uses CRC-16-CCITT; CC1101 uses CRC-16-IBM      |
| Data rate          | 19,200 bps     | Davis ISS spec                                       |
| Modulation         | 2-FSK          | Davis ISS spec                                       |
| Frequency deviation| ~4.8 kHz       | Community-documented value for Davis ISS             |
| RX filter BW       | ~50 kHz        | Covers deviation + oscillator tolerance              |
| APPEND_STATUS      | On             | Appends RSSI and LQI bytes after each packet         |
| Frequency setting  | FREQ2/1/0 direct | Davis channels are not uniformly spaced            |
| GDO0               | Assert on RX packet (`0x01`) | Optional interrupt pin for low-latency reception |

Frequency deviation and RX bandwidth may need empirical tuning — these are the
values most likely to require adjustment for reliable reception.

## Packet Layout

The RTL-SDR path produces 10-byte `pkt.data` arrays:

```
Bytes 0-1:  Preamble  (0xCB 0x89 before bit-reversal)
Bytes 2-9:  Payload   (6 data bytes + 2 CRC bytes)
```

`protocol.parse()` calls `swap_bit_order` on every byte, then validates
`CRC(data[2:]) == 0` and parses `msg_data = data[2:]`.

The CC1101 delivers only the 8 payload bytes (the sync word is consumed by hardware
detection). The driver prepends `0xCB 0x89` to reconstruct the 10-byte layout so
that `protocol.parse()` works without modification.

## Frequency Hopping

Frequency hopping uses the same `Protocol.next_hop()` / `rand_hop()` logic as the
RTL-SDR path. The only difference is the hardware call:

- RTL-SDR: `sdr.center_freq = hop.channel_freq + hop.freq_corr`
- CC1101:  `cc1101.set_frequency(hop.channel_freq)`  (freq_corr is always 0)

Davis channels are not uniformly spaced so the CC1101's CHANNR register cannot be
used; the absolute frequency is written to FREQ2/FREQ1/FREQ0 on each hop.

## Frequency Error Correction

The RTL-SDR path estimates per-hop frequency error from the FSK discriminator's
mean output over the preamble region (`protocol.parse()` line ~300). This requires
access to `self.demodulator.discriminated[]`, which does not exist on the CC1101
path.

For CC1101 packets, `pkt.index` is set to `-1`. `protocol.parse()` skips the
discriminated-signal lookup when `pkt.index < 0` and records `freq_err = 0`.
No micro-correction is applied; the CC1101's crystal oscillator is stable enough
that this is not needed.

## Implementation Checklist

- [x] `RADIO_CC1101.md` — this document
- [x] `src/rtldavis/cc1101.py` — SPI driver and Davis adapter
- [x] `src/rtldavis/protocol.py` — skip freq-error calc when `pkt.index < 0`
- [x] `src/rtldavis/__main__.py` — `--radio` flag and `_main_cc1101_async()`
- [x] `pyproject.toml` — `cc1101 = ["spidev"]` optional dependency

## New Files

### `src/rtldavis/cc1101.py`

Responsibilities:
- SPI communication via `spidev`
- `configure_for_davis()` — writes all register values listed above
- `set_frequency(hz)` — converts Hz to FREQ2/FREQ1/FREQ0 and writes them
- `receive_packet() -> Optional[dsp.Packet]` — reads RXFIFO when a packet is
  available, prepends preamble bytes, converts raw RSSI to dBm and LQI to
  approximate SNR, returns a `dsp.Packet(index=-1, ...)`
- `rssi_to_dbm(raw)` — CC1101 formula: `raw/2 - 74` (above -64) or
  `(raw + 256)/2 - 74` (below -64)
- `lqi_to_snr(lqi)` — `(lqi & 0x7F) / 2.55` as a rough 0–50 dB proxy

## Changed Files

### `src/rtldavis/protocol.py`

One change in `parse()`: guard the discriminated-signal frequency error block:

```python
if pkt.index >= 0:
    preamble_samples = self.demodulator.discriminated[preamble_start:preamble_end]
    mean = np.mean(preamble_samples)
    freq_err = -int((mean * float(self.cfg.sample_rate)) / (2 * math.pi))
else:
    freq_err = 0
```

### `src/rtldavis/__main__.py`

- Add `--radio {rtlsdr,cc1101}` (default: `rtlsdr`)
- Add `--cc1101-spi-bus INT` (default: 0)
- Add `--cc1101-spi-device INT` (default: 0)
- Add `--cc1101-gdo0-pin INT` (optional; enables interrupt-driven reception)
- Add `main_cc1101_async()` — same hop/scan/missed-packet structure as the
  existing loop, but replaces `sdr.stream()` with a SPI poll/interrupt loop and
  `sdr.center_freq =` with `cc1101.set_frequency()`

### `pyproject.toml`

```toml
[project.optional-dependencies]
test   = ["pytest~=9.0"]
cc1101 = ["spidev"]
```

## Hardware Wiring — Raspberry Pi 4 Protoboard Hat

### Pin mapping

Most CC1101 breakout modules have an 8-pin header.

#### Single-Row Pinout

For modules with a single row of 8 pins (looking at the component side, pin 1 marked or nearest the antenna):

```
CC1101 module pin   Signal    Pi 40-pin header    BCM GPIO
─────────────────────────────────────────────────────────
1  VCC             3.3 V     Pin 1  (3V3)         —
2  GND             Ground    Pin 6  (GND)          —
3  MOSI            SPI data  Pin 19 (SPI0_MOSI)   GPIO 10
4  MISO            SPI data  Pin 21 (SPI0_MISO)   GPIO 9
5  SCK             SPI clock Pin 23 (SPI0_SCLK)   GPIO 11
6  CSN             Chip sel. Pin 26 (SPI0_CE1_N)  GPIO 7
7  GDO0            RX ready  Pin 22               GPIO 25  (optional)
8  GDO2            unused    —                    —
```

#### Double-Row (2x4) Pinout

For modules with a 2x4 double-row header (top view, pins run 7→1 down the left edge, 8→2 down the right edge):

```
                     ┌─────────────┐
  MISO ── GPIO 9  ───┤ 7         8 ├─── (unused)── GDO2
   SCK ── GPIO 11 ───┤ 5         6 ├─── GPIO 10 ── MOSI
  GDO0 ── GPIO 25 ───┤ 3         4 ├─── GPIO 7  ── CSN
   GND ── GND     ───┤ 1         2 ├─── 3.3V    ── VCC
                     └─────────────┘
                          CC1101
```

CSN on pin 26 = `--cc1101-spi-bus 0 --cc1101-spi-device 1` (required because the eink HAT uses CE0).

### Protoboard layout

The Pi 4 40-pin header runs along one long edge of the board. The SPI0 pins are
all clustered on rows 19–24, which makes it practical to mount the CC1101 module
directly alongside them with short jumper wires:

```
Pi header (odd pins left, even pins right)
                    ┌──────────────────────────────────────────┐
               3V3  │  1 ●  ● 2  │ 5V                          │
         (SDA) GPIO2│  3    ● 4  │ 5V                          │
         (SCL) GPIO3│  5    ● 6  │ GND  ←─────────────── GND  ─┤ CC1101
               GPIO4│  7    ● 8  │ TX                           │  pin 2
               GND  │  9 ● ●10  │ RX                           │
              GPIO17│ 11   ●12  │ GPIO18                        │
              GPIO27│ 13   ●14  │ GND                           │
              GPIO22│ 15   ●16  │ GPIO23                        │
               3V3  │ 17 ● ●18  │ GPIO24         3V3 ───────── │ CC1101
      MOSI GPIO10  │ 19 ● ●20  │ GND             pin 1         │  pin 1
      MISO GPIO9   │ 21 ● ●22  │ GPIO25  ←── GDO0 (optional) ──┤ CC1101
      SCLK GPIO11  │ 23 ● ●24  │ CE0                           │  pin 7
               GND  │ 25   ●26  │ CE1                           │
              GPIO0 │ 27   ●28  │ GPIO1                         │
              GPIO5 │ 29   ●30  │ GND                           │
              GPIO6 │ 31   ●32  │ GPIO12                        │
             GPIO13 │ 33   ●34  │ GND                           │
             GPIO19 │ 35   ●36  │ GPIO16                        │
             GPIO26 │ 37   ●38  │ GPIO20                        │
               GND  │ 39   ●40  │ GPIO21                        │
                    └──────────────────────────────────────────┘

  Pi pin 19 (MOSI / GPIO10) ──────────────────────────── CC1101 pin 3 (MOSI)
  Pi pin 21 (MISO / GPIO9)  ──────────────────────────── CC1101 pin 4 (MISO)
  Pi pin 23 (SCLK / GPIO11) ──────────────────────────── CC1101 pin 5 (SCK)
  Pi pin 26 (CE1  / GPIO7)  ──────────────────────────── CC1101 pin 6 (CSN)
```

### Notes

- **3.3 V only.** The CC1101 and its SPI lines are 3.3 V. The Pi 4 GPIO is also
  3.3 V, so no level shifting is needed. Never connect VCC to a 5 V pin.
- **Antenna.** Solder a 82 mm wire to the ANT pad for 915 MHz (quarter-wave). A
  proper helical or whip antenna will improve range significantly.
- **Decoupling.** Place a 100 nF ceramic cap between VCC and GND close to the
  module to suppress SPI-induced noise on the 3.3 V rail.
- **GDO0 is optional.** Without it the driver polls the RXBYTES status register
  every 10 ms, which is plenty fast for Davis's 2.5 s transmit interval. Wire it
  if you want sub-millisecond packet latency or plan to add interrupt-driven
  reception later.

## Running on the Pi

To run `rtldavis` using the CC1101 radio (on `CE1` to avoid the e-ink conflict) and simultaneously poll the local BME280 sensor over I2C, use the following one-liner:

```bash
uv run rtldavis --radio cc1101 --cc1101-spi-device 1 --bme280
```
