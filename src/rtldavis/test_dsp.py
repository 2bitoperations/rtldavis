import unittest
import numpy as np

from . import dsp
from . import protocol

class TestDSP(unittest.TestCase):
    def test_full_pipeline(self):
        # This test simulates a full pipeline from IQ samples to a decoded message.
        # We will construct a valid "Temperature" packet for 75.0 F.

        # 1. Create a valid packet payload and CRC
        p = protocol.Parser(symbol_length=14)
        
        # This is the 6-byte payload for a Temperature packet.
        payload = bytearray([
            0x82,  # Sensor type 8 (Temp), station ID 2
            0x00,  # Wind speed
            0x00,  # Wind direction
            0x02,  # Temp high byte
            0xEE,  # Temp low byte (0x02EE = 750 -> 75.0F)
            0x00,  # Unknown/unused byte
        ])

        # To create a valid CRC block where checksum is 0, we calculate the CRC
        # of the payload padded with two zero bytes. The result is the CRC.
        crc_val = p.crc.checksum(payload + b'\x00\x00')
        crc_bytes = int(crc_val).to_bytes(2, 'big')
        
        # The CRC block is the payload followed by the calculated CRC.
        crc_block = payload + crc_bytes
        
        # The full 10-byte packet includes a 2-byte header not covered by CRC.
        packet_data = bytearray([0x00, 0x00]) + crc_block

        # 2. Create a bitstream from the packet
        cfg = p.cfg
        
        # Create the bitstream as it should appear *after* demodulation and quantization.
        # First, reverse the bits in each byte to match what the parser expects after slicing.
        expected_packet_bits = np.unpackbits(np.frombuffer(packet_data, dtype=np.uint8))
        expected_packet_bits = expected_packet_bits.reshape(-1, 8)[:, ::-1].flatten()
        
        # The preamble is what the search function looks for.
        expected_preamble_bits = np.array([int(b) for b in cfg.preamble], dtype=np.uint8)
        
        # Add some lead-in bits to allow the filter to settle.
        # This prevents the transient response from corrupting the preamble.
        leadin_bits = np.tile([1, 0], 16) # 32 bits of alternating 1/0
        
        # This is the full bitstream we expect to see in the `quantized` buffer.
        # Note: The lead-in is not part of the "expected" packet structure for parsing,
        # but it is part of the signal we generate.
        signal_bits = np.concatenate((leadin_bits, expected_preamble_bits, expected_packet_bits))
        
        # 3. Create a fake FSK signal with the bitstream
        symbol_length = cfg.symbol_length
        num_samples = len(signal_bits) * symbol_length
        samples = np.zeros(num_samples, dtype=np.float64)
        
        current_phase = 0.0
        # Use a phase shift to represent frequency shift for FSK.
        # IMPORTANT: The DSP `quantize` function outputs 0 for positive frequency (val >= 0)
        # and 1 for negative frequency (val < 0).
        # So:
        # Bit 1 -> Negative Frequency -> val < 0 -> Quantized 1
        # Bit 0 -> Positive Frequency -> val > 0 -> Quantized 0
        phase_step_val = np.pi / 4
        for i, bit in enumerate(signal_bits):
            # If bit is 1, we want negative frequency shift.
            # If bit is 0, we want positive frequency shift.
            phase_step = -phase_step_val if bit == 1 else phase_step_val
            
            start = i * symbol_length
            end = start + symbol_length
            
            phase_ramp = np.cumsum(np.full(symbol_length, phase_step))
            samples[start:end] = current_phase + phase_ramp
            current_phase = samples[end-1]

        # 4. Create a complex signal from the phase profile
        iq_samples = np.exp(1j * samples)

        # 5. Run the demodulator in chunks
        demod = dsp.Demodulator(cfg)
        packets = []
        # Pad the signal to ensure all data is flushed through the filters.
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
        self.assertAlmostEqual(msg.temperature, 75.0)
        
if __name__ == '__main__':
    unittest.main()
