"""
Diagnostic Tool: scratch_freq.py
Experimental script used to reverse engineer the Davis protocol frequency hopping patterns.
"""
import sys
import os
sys.path.insert(0, os.path.abspath('src'))
from rtldavis.protocol import Parser
p = Parser(14)
hop_idx = p.hop_pattern.index(0)
hop = p.set_hop(hop_idx, p.transmitter)
print(hop.channel_freq)
