"""
CC1101 SPI driver and Davis ISS adapter.

Communicates with a TI CC1101 transceiver over SPI (via spidev) and
presents received Davis ISS packets as dsp.Packet objects compatible
with protocol.parse().
"""

import logging
import time
from typing import Optional

import numpy as np

from . import dsp

logger = logging.getLogger(__name__)

# ── CC1101 SPI command strobes ──────────────────────────────────────────────

_SRES   = 0x30  # Reset chip
_SFSTXON= 0x31  # Enable/calibrate freq synth
_SXOFF  = 0x32  # Turn off crystal oscillator
_SCAL   = 0x33  # Calibrate freq synth and turn off
_SRX    = 0x34  # Enable RX
_STX    = 0x35  # Enable TX
_SIDLE  = 0x36  # Exit RX/TX, turn off freq synth
_SFRX   = 0x3A  # Flush RX FIFO
_SFTX   = 0x3B  # Flush TX FIFO
_SNOP   = 0x3D  # No operation (returns chip status)

# ── CC1101 register addresses ────────────────────────────────────────────────

_IOCFG0   = 0x02
_FIFOTHR  = 0x03
_SYNC1    = 0x04
_SYNC0    = 0x05
_PKTLEN   = 0x06
_PKTCTRL1 = 0x07
_PKTCTRL0 = 0x08
_FSCTRL1  = 0x0B
_FREQ2    = 0x0D
_FREQ1    = 0x0E
_FREQ0    = 0x0F
_MDMCFG4  = 0x10
_MDMCFG3  = 0x11
_MDMCFG2  = 0x12
_MDMCFG1  = 0x13
_MDMCFG0  = 0x14
_DEVIATN  = 0x15
_MCSM1    = 0x17
_MCSM0    = 0x18
_FOCCFG   = 0x19
_BSCFG    = 0x1A
_AGCCTRL2 = 0x1B
_AGCCTRL1 = 0x1C
_AGCCTRL0 = 0x1D
_FSCAL3   = 0x23
_FSCAL2   = 0x24
_FSCAL1   = 0x25
_FSCAL0   = 0x26
_TEST2    = 0x2C
_TEST1    = 0x2D
_TEST0    = 0x2E

# ── CC1101 read-only status registers (accessed with burst bit set) ──────────

_RSSI     = 0x74  # Received signal strength indicator
_MARCSTATE= 0x75  # Main Radio Control State Machine state
_RXBYTES  = 0x7B  # Number of bytes in RX FIFO
_RXFIFO   = 0xFF  # RX FIFO burst read address (0x3F | 0xC0)

# Davis ISS preamble as bytes (before bit-reversal by protocol.swap_bit_order)
_DAVIS_PREAMBLE = bytes([0xCB, 0x89])

# Davis packet payload length (bytes after sync word, including 2-byte CRC)
_DAVIS_PAYLOAD_LEN = 8

# CC1101 crystal frequency (26 MHz on virtually all modules)
_XTAL_HZ = 26_000_000


def _rssi_to_dbm(raw: int) -> float:
    """Convert raw CC1101 RSSI byte to dBm."""
    if raw >= 128:
        return (raw - 256) / 2.0 - 74.0
    return raw / 2.0 - 74.0


def _lqi_to_snr(lqi: int) -> float:
    """Map CC1101 LQI (0-127, higher = better) to a rough SNR proxy in dB."""
    return (lqi & 0x7F) / 2.55


class CC1101:
    """
    TI CC1101 sub-1 GHz transceiver driver for Davis ISS reception.

    Usage:
        radio = CC1101(spi_bus=0, spi_device=0)
        radio.open()
        radio.configure_for_davis()
        radio.set_frequency(902_419_338)
        pkt = radio.receive_packet()  # returns None if nothing ready
        radio.close()
    """

    def __init__(self, spi_bus: int = 0, spi_device: int = 0) -> None:
        self._bus = spi_bus
        self._device = spi_device
        self._spi = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def open(self) -> None:
        try:
            import spidev
        except ImportError as e:
            raise RuntimeError(
                "spidev is required for CC1101 support. "
                "Install it with: pip install spidev"
            ) from e

        self._spi = spidev.SpiDev()
        self._spi.open(self._bus, self._device)
        self._spi.max_speed_hz = 4_000_000
        self._spi.mode = 0
        logger.info(f"SPI opened: bus={self._bus} device={self._device}")

        self._reset()
        
        # Verify SPI wiring by reading hardware registers
        partnum = self._read_status(0x30)
        version = self._read_status(0x31)
        
        if partnum == 0x00 and version == 0x00:
            raise RuntimeError("CC1101 SPI readback failed (all 0x00). Is MISO disconnected or shorted to GND?")
        if partnum == 0xFF and version == 0xFF:
            raise RuntimeError("CC1101 SPI readback failed (all 0xFF). Is MISO floating or shorted to 3.3V?")
            
        logger.warning(f"CC1101 hardware detected: PARTNUM=0x{partnum:02X}, VERSION=0x{version:02X}")

    def close(self) -> None:
        if self._spi is not None:
            self._strobe(_SIDLE)
            self._spi.close()
            self._spi = None

    # ── Configuration ─────────────────────────────────────────────────────────

    def configure_for_davis(self) -> None:
        """Write all registers needed for Davis ISS reception."""
        self._strobe(_SIDLE)

        regs = [
            # GDO0: assert when RX FIFO at or above threshold (packet received)
            (_IOCFG0,   0x01),
            # RX FIFO threshold: 4 bytes (fires well before 10-byte packet fills)
            (_FIFOTHR,  0x00),
            # Sync word = Davis preamble 0xCB89
            (_SYNC1,    0xCB),
            (_SYNC0,    0x89),
            # Fixed packet length = 8 bytes
            (_PKTLEN,   _DAVIS_PAYLOAD_LEN),
            # PKTCTRL1: append RSSI+LQI status bytes, no address check
            (_PKTCTRL1, 0x04),
            # PKTCTRL0: no whitening, no CRC, fixed packet length
            (_PKTCTRL0, 0x00),
            # FSCTRL1: IF frequency = 152.34 kHz
            (_FSCTRL1,  0x06),
            # MDMCFG4: channel BW 325 kHz (maximum width for drift)
            #   0x59 = CHANBW_E=1, CHANBW_M=1, DRATE_E=9 → ~325 kHz BW
            (_MDMCFG4,  0x59),
            # MDMCFG3: DRATE_M for 19,200 bps
            #   DRATE = XTAL * (256+DRATE_M) * 2^DRATE_E / 2^28
            #   DRATE_E=9 (from MDMCFG4), DRATE_M=131 (0x83) → 19,199.7 bps ≈ 19,200
            (_MDMCFG3,  0x83),
            # MDMCFG2: 16/16 sync word bits (strict match)
            (_MDMCFG2,  0x02),
            # MDMCFG1: 4 preamble bytes, no FEC
            (_MDMCFG1,  0x22),
            # MDMCFG0: channel spacing (not used for Davis hopping, but required)
            (_MDMCFG0,  0xF8),
            # DEVIATN: frequency deviation ~4.8 kHz
            #   DEV = XTAL * (8 + DEV_M) * 2^DEV_E / 2^17
            #   DEV_E=2, DEV_M=0 → ~3.05 kHz  (start conservative, tune upward)
            (_DEVIATN,  0x15),
            # MCSM1: stay in RX after packet received
            (_MCSM1,    0x3F),
            # MCSM0: auto-calibrate when going from IDLE to RX
            (_MCSM0,    0x18),
            # FOCCFG: frequency offset compensation
            (_FOCCFG,   0x16),
            # BSCFG: bit synchronisation (Maximized loop bandwidth for ultra-fast lock)
            (_BSCFG,    0xFC),
            # AGCCTRL2/1/0: AGC settings suitable for FSK
            (_AGCCTRL2, 0x43),
            (_AGCCTRL1, 0x40),
            # AGCCTRL0: Halved wait time to let AGC settle faster during short preamble
            (_AGCCTRL0, 0x81),
            # Calibration / test registers (SmartRF Studio recommended values)
            (_FSCAL3,   0xE9),
            (_FSCAL2,   0x2A),
            (_FSCAL1,   0x00),
            (_FSCAL0,   0x1F),
            
            # CRITICAL: TEST registers must be set for 915 MHz operation
            # per TI CC1101 Datasheet Section 28.2
            (_TEST2,    0x81),
            (_TEST1,    0x35),
            (_TEST0,    0x09),
        ]

        for addr, value in regs:
            self._write_reg(addr, value)

        logger.info("CC1101 configured for Davis ISS reception")

    def set_frequency(self, hz: int) -> None:
        """Set the CC1101 carrier frequency in Hz."""
        # We MUST enter IDLE mode before changing frequency registers so that
        # when we re-enter RX mode, the PLL is forced to recalibrate.
        self._strobe(_SIDLE)
        
        freq_word = int(hz * (1 << 16) / _XTAL_HZ)
        self._write_reg(_FREQ2, (freq_word >> 16) & 0xFF)
        self._write_reg(_FREQ1, (freq_word >> 8) & 0xFF)
        self._write_reg(_FREQ0, freq_word & 0xFF)
        
        # Strobe back into receive mode (triggers FS_AUTOCAL)
        self._strobe(_SRX)
        logger.debug(f"CC1101 frequency set to {hz} Hz (word=0x{freq_word:06X})")

    def start_rx(self) -> None:
        self._strobe(_SRX)

    # ── Packet reception ──────────────────────────────────────────────────────

    def receive_packet(self) -> Optional[dsp.Packet]:
        """
        Read one packet from the RX FIFO if available.

        Returns a dsp.Packet with index=-1 (signals no DSP/discriminated data)
        or None if no complete packet is waiting.
        """
        rxbytes = self._read_status(_RXBYTES)
        
        if rxbytes & 0x80:
            # RX FIFO overflow! The CC1101 freezes reception until flushed.
            logger.warning("CC1101 RX FIFO Overflow! Flushing.")
            self.flush_rx()
            return None
            
        rxbytes &= 0x7F
        expected = _DAVIS_PAYLOAD_LEN + 2  # payload + appended RSSI/LQI
        if rxbytes < expected:
            return None

        raw = self._read_burst(0x3F, expected)
        if len(raw) < expected:
            logger.warning(f"Short read from RXFIFO: got {len(raw)}, expected {expected}")
            self._strobe(_SFRX)
            self._strobe(_SRX)
            return None

        # The protocol parser expects the 2-byte sync word (0xCB89) to be present at the start of the payload
        # because the RTL-SDR passes the raw unstripped bitstream. The CC1101 hardware strips the sync word.
        # We prepend it here to maintain compatibility with the dsp.Packet format so CRC checks pass!
        payload = bytes([0xCB, 0x89]) + bytes(raw[:_DAVIS_PAYLOAD_LEN])
        
        rssi_raw = raw[_DAVIS_PAYLOAD_LEN]
        lqi_raw  = raw[_DAVIS_PAYLOAD_LEN + 1]

        # Status byte bit 7: CRC_OK (always 1 since we disabled HW CRC,
        # meaning the bit instead reflects "packet length matched")
        rssi = _rssi_to_dbm(rssi_raw)
        snr = _lqi_to_snr(lqi_raw)

        return dsp.Packet(
            index=-1,
            data=np.array(list(payload), dtype=np.uint8),
            rssi=rssi,
            snr=snr
        )

    def transmit_packet(self, data: bytes) -> None:
        """
        Transmit a raw payload. Data must be exactly _DAVIS_PAYLOAD_LEN bytes.
        The CC1101 will automatically prepend the 4-byte preamble and 0xCB89 sync word.
        """
        if len(data) != _DAVIS_PAYLOAD_LEN:
            raise ValueError(f"Payload must be {_DAVIS_PAYLOAD_LEN} bytes")
            
        self._strobe(_SIDLE)
        self._strobe(_SFTX) # Flush TX FIFO
        
        # Write payload to TX FIFO (burst access to 0x3F)
        self._write_burst(0x3F, list(data))
        
        # Start TX
        self._strobe(_STX)
        
        # Wait until transmission completes
        # MARCSTATE: 1=IDLE, 13=RX, 19=TX
        # Since TXOFF_MODE is 11 (Stay in RX), it will go to RX (13) after TX!
        while True:
            state = self._read_status(_MARCSTATE) & 0x1F
            if state in (1, 13, 14, 15):  # Returned to IDLE or transitioned to RX
                break
            time.sleep(0.001)

    def debug_state(self) -> dict:
        """Dump the hardware state machine, RSSI, and any raw bytes stranded in the RX FIFO."""
        marcstate = self._read_status(_MARCSTATE) & 0x1F
        
        rssi_dec = self._read_status(_RSSI)
        if rssi_dec >= 128:
            rssi_dBm = (rssi_dec - 256) / 2.0 - 74.0
        else:
            rssi_dBm = rssi_dec / 2.0 - 74.0
            
        rxbytes = self._read_status(_RXBYTES)
        fifo_count = rxbytes & 0x7F
        overflow = bool(rxbytes & 0x80)
        
        dump = b""
        if fifo_count > 0:
            dump = bytes(self._read_burst(0x3F, fifo_count))
            
        if overflow:
            self.flush_rx()
            
        return {
            "MARCSTATE": marcstate, 
            "RSSI_dBm": rssi_dBm, 
            "RXBYTES": fifo_count,
            "OVERFLOW": overflow,
            "FIFO_DUMP": dump.hex()
        }

        # Status byte bit 7: CRC_OK (always 1 since we disabled HW CRC,
        # meaning the bit instead reflects "packet length matched")
        rssi = _rssi_to_dbm(rssi_raw)
        snr  = _lqi_to_snr(lqi_raw)

        # Reconstruct the 10-byte layout protocol.parse() expects:
        # [preamble_byte0, preamble_byte1, payload_0 … payload_7]
        data_bytes = _DAVIS_PREAMBLE + payload
        data = __import__("numpy").frombuffer(data_bytes, dtype=__import__("numpy").uint8)

        logger.debug(f"CC1101 packet: {payload.hex()} RSSI={rssi:.1f} dBm LQI={lqi_raw & 0x7F}")

        return dsp.Packet(index=-1, data=data, rssi=rssi, snr=snr)

    def flush_rx(self) -> None:
        self._strobe(_SIDLE)
        self._strobe(_SFRX)
        self._strobe(_SRX)

    # ── Low-level SPI helpers ─────────────────────────────────────────────────

    def _reset(self) -> None:
        self._strobe(_SRES)
        time.sleep(0.01)
        logger.debug("CC1101 reset")

    def _strobe(self, cmd: int) -> int:
        result = self._spi.xfer2([cmd])
        return result[0]

    def _write_reg(self, addr: int, value: int) -> None:
        self._spi.xfer2([addr & 0x3F, value])

    def _read_reg(self, addr: int) -> int:
        result = self._spi.xfer2([addr | 0x80, 0x00])
        return result[1]

    def _read_status(self, addr: int) -> int:
        # Status registers require burst flag (0xC0)
        result = self._spi.xfer2([addr | 0xC0, 0x00])
        return result[1]

    def _read_burst(self, addr: int, length: int) -> list[int]:
        # Burst read: addr | 0xC0, then clock out `length` dummy bytes
        cmd = [addr | 0xC0] + [0x00] * length
        result = self._spi.xfer2(cmd)
        return result[1:]

    def _write_burst(self, addr: int, data: list[int]) -> None:
        # Burst write: addr | 0x40
        cmd = [addr | 0x40] + data
        self._spi.xfer2(cmd)
