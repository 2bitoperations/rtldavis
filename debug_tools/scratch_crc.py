"""
Diagnostic Tool: scratch_crc.py
Experimental script used to reverse engineer the Davis protocol CRC algorithm.
"""
import sys
import os
sys.path.insert(0, os.path.abspath('src'))
from rtldavis.protocol import Parser
from rtldavis.crc import CRC
crc = CRC(name="CCITT", init=0x0000, poly=0x1021, residue=0x0000)
data = bytes([0x81, 0x05, 0x8D, 0x33, 0xCB, 0x0F, 0xF1, 0xDD])
print("CRC:", crc.checksum(data))
