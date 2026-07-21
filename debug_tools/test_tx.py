"""
Diagnostic Tool: test_tx.py
Configures the CC1101 in transmit mode and repeatedly sends a mock Davis ISS FSK packet to verify TX capabilities and FSK bit polarity.
"""
import time
import logging
from rtldavis.cc1101 import CC1101

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("test_tx")

def swap_bit_order(b: int) -> int:
    return int('{:08b}'.format(b)[::-1], 2)

def main():
    logger.info("Initializing CC1101 for TX Testing...")
    cc = CC1101(spi_bus=0, spi_device=1)
    cc.open()
    cc.configure_for_davis()
    
    # Configure Power Amplifier (PATABLE)
    # The CC1101 boots with PATABLE[0] = 0x00 (power off).
    # 0x03 configures it for -30 dBm minimum output power to prevent SDR ADC clipping!
    cc._write_reg(0x3E, 0x03)
    logger.info("Power Amplifier set to -30 dBm (minimum power)")
    
    # Choose a fixed frequency (Channel 0 of the Davis hopping sequence)
    # rtl_433 analysis showed the actual RF emission is centered at -32.6 kHz
    # relative to 902.419 MHz! This means the CC1101's 26 MHz crystal has a -36 PPM error.
    # The rtldavis SDR uses a very narrow FIR filter centered at 0 Hz baseband, so the
    # signal was completely rejected by the filter, resulting in random garbage!
    # We compensate by requesting a frequency 32600 Hz HIGHER.
    freq = 902419338 + 32600
    cc.set_frequency(freq)
    logger.info(f"Tuned transmitter to {freq} Hz (compensated for -32.6 kHz crystal error)")
    # Known good Davis ISS packet (Temperature: 82.9 F, Wind: 5 mph)
    raw_payload = bytes([0x81, 0x05, 0x8D, 0x33, 0xCB, 0x0F, 0xF1, 0xDD])
    
    # Because Davis transmits LSB-first but CC1101 transmits MSB-first,
    # we must bit-reverse the payload so it hits the air exactly like a Davis transmitter!
    payload = bytes([swap_bit_order(b) for b in raw_payload])
    
    # CC1101 requires specific, undocumented TEST register values for TX at 915 MHz
    cc._write_reg(0x2C, 0x88) # TEST2
    cc._write_reg(0x2D, 0x31) # TEST1
    
    # Configure baud rate and deviation
    cc._write_reg(0x15, 0x24) # DEVIATN: 9.5 kHz
    cc._write_reg(0x10, 0x59) # MDMCFG4: CHANBW_E=1, CHANBW_M=1, DRATE_E=9
    cc._write_reg(0x11, 0x83) # MDMCFG3: DRATE_M=131
    
    # Use standard Sync Word
    cc._write_reg(0x04, 0xCB) # SYNC1
    cc._write_reg(0x05, 0x89) # SYNC0
    
    logger.info("Configured VCO TEST registers for TX mode and forced 9.5 kHz Deviation / 19.2 kbps Baud Rate")
    
    logger.info("=========================================================")
    logger.info("Transmitter is live!")
    logger.info("Leave this script running, and open a NEW terminal.")
    logger.info("In the new terminal, run: uv run rtldavis")
    logger.info("The RTL-SDR will scan, find this signal, and decode it.")
    logger.info("=========================================================")
    
    seq = 0
    try:
        while True:
            state_before = cc._read_status(0x35) & 0x1F # MARCSTATE
            
            cc._strobe(0x36) # SIDLE
            time.sleep(0.001)
            cc._strobe(0x3B) # SFTX
            
            cc._write_burst(0x3F, list(payload))
            txbytes_before = cc._read_status(0x3A) & 0x7F # TXBYTES
            
            cc._strobe(0x35) # STX
            time.sleep(0.005) # Wait 5ms for TX to finish (packet is 4.1ms)
            
            state_after = cc._read_status(0x35) & 0x1F # MARCSTATE
            txbytes_after = cc._read_status(0x3A) & 0x7F # TXBYTES
            
            seq += 1
            if seq % 10 == 0:
                logger.info(f"[{seq}] State Before={state_before}, TXBytes Loaded={txbytes_before}, State After={state_after}, TXBytes Remaining={txbytes_after}")
            time.sleep(0.1)
    except KeyboardInterrupt:
        logger.info("Stopping transmitter.")
    finally:
        cc.close()

if __name__ == "__main__":
    main()
