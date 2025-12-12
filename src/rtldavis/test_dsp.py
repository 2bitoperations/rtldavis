import unittest
import numpy as np

from . import dsp
from . import protocol

class TestDSP(unittest.TestCase):
    def test_full_pipeline(self):
        # This is a known valid packet from the original Go code's test suite.
        # It's a "Temperature" packet with a value of 75.0 F.
        # The raw data is:
        # 0x82, 0x9A, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
        # The CRC is calculated over the last 8 bytes.
        
        # 1. Create a known packet
        packet_data = bytearray([
            0x82, 0x9A, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
        ])
        
        # Manually calculate the CRC of the data part
        p = protocol.Parser(symbol_length=14)
        crc = p.crc.checksum(packet_data[2:])
        
        # The Go code expects the CRC to be 0, so we need to append the CRC
        # to the packet data.
        packet_data.extend(int(crc).to_bytes(2, 'big'))

        # 2. Create a bitstream from the packet
        cfg = p.cfg
        
        # We need to reverse the bits in each byte to simulate over-the-air transmission
        # The protocol parser will reverse them back.
        packet_bits = np.unpackbits(np.frombuffer(packet_data, dtype=np.uint8))
        packet_bits = packet_bits.reshape(-1, 8)[:, ::-1].flatten()
        
        preamble = np.array([1, 1, 0, 0, 1, 0, 1, 1, 1, 0, 0, 0, 1, 0, 0, 1], dtype=np.uint8)
        bits = np.concatenate((preamble, packet_bits))
        
        # 3. Create a fake signal with the bitstream
        # We'll create a simple FSK signal where 0 is a negative frequency shift
        # and 1 is a positive frequency shift.
        symbol_length = cfg.symbol_length
        num_samples = len(bits) * symbol_length
        samples = np.zeros(num_samples, dtype=np.float64)
        
        current_phase = 0.0
        for i, bit in enumerate(bits):
            # The Go code uses a phase shift of +/- pi/4 per sample.
            # This corresponds to a frequency shift of +/- fs/8.
            phase_step = np.pi / 4 if bit == 1 else -np.pi / 4
            
            start = i * symbol_length
            end = start + symbol_length
            
            # Generate phase for this symbol
            phase_ramp = np.cumsum(np.full(symbol_length, phase_step))
            samples[start:end] = current_phase + phase_ramp
            current_phase = samples[end-1]

        # 4. Create a complex signal from the fake signal
        # We'll create a simple complex signal with a constant magnitude
        iq_samples = np.exp(1j * samples)

        # 5. Run the demodulator in chunks
        demod = dsp.Demodulator(cfg)
        packets = []
        # We need to pad the signal with some zeros to flush the filters
        padding = np.zeros(cfg.block_size * 2, dtype=np.complex128)
        iq_samples = np.concatenate((iq_samples, padding))

        for i in range(0, len(iq_samples), cfg.block_size):
            chunk = iq_samples[i : i + cfg.block_size]
            if len(chunk) == cfg.block_size:
                packets.extend(demod.demodulate(chunk))
        
        # 6. Parse the packets
        parser = protocol.Parser(symbol_length=14)
        messages = parser.parse(packets)
        
        # 7. Check the results
        self.assertGreater(len(messages), 0, "No messages decoded")
        msg = messages[0]
        self.assertEqual(msg.sensor, protocol.Sensor.TEMPERATURE)
        
if __name__ == '__main__':
    unittest.main()
