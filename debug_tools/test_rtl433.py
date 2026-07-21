"""
Diagnostic Tool: test_rtl433.py
Invokes the `rtl_433` pulse analyzer to profile the exact timing, deviation, and pulse widths of the CC1101 FSK transmission.
"""
import time
import logging
from src.rtldavis.cc1101 import CC1101

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def main():
    cc = CC1101(spi_bus=0, spi_device=1)
    cc.open()
    cc.configure_for_davis()
    
    # -30 dBm to prevent SDR clipping
    cc._write_reg(0x3E, 0x03) 
    
    cc._write_reg(0x2C, 0x88) # TEST2
    cc._write_reg(0x2D, 0x31) # TEST1
    
    # 902.419 MHz + 32.6 kHz offset for CC1101 crystal
    freq = 902419338 + 32600
    cc.set_frequency(freq)
    
    # 19.2 kbps, 9.5 kHz deviation
    cc._write_reg(0x15, 0x24)
    cc._write_reg(0x10, 0x59)
    cc._write_reg(0x11, 0x83)
    
    # SYNC word = AA AA
    cc._write_reg(0x04, 0xAA)
    cc._write_reg(0x05, 0xAA)
    
    # Payload = 12 34 56 78 9A BC DE F0
    payload = bytes([0x12, 0x34, 0x56, 0x78, 0x9A, 0xBC, 0xDE, 0xF0])
    
    logger.info("Transmitting recognizable pattern continuously...")
    while True:
        cc._strobe(0x36) # SIDLE
        time.sleep(0.005)
        cc._strobe(0x3B) # SFTX
        cc._write_burst(0x3F, list(payload))
        cc._strobe(0x35) # STX
        
        while True:
            marc = cc._read_status(0x35) & 0x1F
            if marc == 1: # IDLE
                break
            time.sleep(0.001)
            
        time.sleep(0.2)

if __name__ == '__main__':
    main()
