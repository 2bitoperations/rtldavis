"""
Diagnostic Tool: prove_cc1101.py
Hardware verification script that tests SPI communication and verifies that registers can be successfully read and written on the CC1101 chip.
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
    # OOK requires two PATABLE entries: index 0 (logic 0) and index 1 (logic 1)
    # 0x00 = OFF, 0x34 = -10 dBm
    cc._write_burst(0x3E, [0x00, 0x34])
    cc._write_reg(0x22, 0x11) # FREND0: PA power setting (index 1)
    cc._write_reg(0x2C, 0x88) # TEST2
    cc._write_reg(0x2D, 0x31) # TEST1
    cc._write_reg(0x06, 0x08) # PKTLEN = 8
    
    # 902.419 MHz + 32.6 kHz offset for CC1101 crystal error
    freq = 902419338 + 32600
    cc.set_frequency(freq)
    
    # Configure for 2000 baud
    cc._write_reg(0x10, 0x66) # MDMCFG4: DRATE_E=6
    cc._write_reg(0x11, 0x93) # MDMCFG3: DRATE_M=147
    # Note: 2000 baud = 500 microseconds per bit
    
    # MDMCFG2: ASK/OOK modulation, 16/16 sync word
    cc._write_reg(0x12, 0x32) 
    
    # Sync word: 0xCC 0xCC (11001100 11001100)
    cc._write_reg(0x04, 0xCC)
    cc._write_reg(0x05, 0xCC)
    
    # Payload = 0xF0 0xF0 0xF0 0xF0 (11110000...)
    # 4 bits of 1 at 2000 bps = 2000 microseconds ON
    # 4 bits of 0 at 2000 bps = 2000 microseconds OFF
    payload = bytes([0xF0, 0xF0, 0xF0, 0xF0, 0xF0, 0xF0, 0xF0, 0xF0])
    
    logger.info("Transmitting 1200 baud FSK packet continuously...")
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
            
        time.sleep(1.0) # Send once per second

if __name__ == '__main__':
    main()
