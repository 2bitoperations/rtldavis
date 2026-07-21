"""
Diagnostic Tool: scratch_burst.py
Experimental script used to reverse engineer and test burst transmission algorithms.
"""
import sys
import os
sys.path.insert(0, os.path.abspath('src'))
from rtldavis.cc1101 import CC1101
cc = CC1101(0, 1)
cc.open()
cc.configure_for_davis()
cc._strobe(0x36) # SIDLE
cc._strobe(0x3B) # SFTX
data = [0xAA, 0xBB, 0xCC, 0xDD]
cc._write_burst(0x3F, data)
status = cc._read_status(0x3A) # TXBYTES
print(f"TXBYTES: {status & 0x7F}")
