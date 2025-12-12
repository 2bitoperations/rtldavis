import numpy as np
import logging
from typing import List, NamedTuple
import struct
import math

logger = logging.getLogger(__name__)

class Packet(NamedTuple):
    index: int
    data: np.ndarray
    rssi: float
    snr: float

class ByteToCmplxLUT:
    """
    A lookup table to convert byte values from the RTL-SDR to complex numbers.
    """
    def __init__(self) -> None:
        self.lut: np.ndarray = (np.arange(256, dtype=np.float64) - 127.4) / 127.6

    def execute(self, in_bytes: np.ndarray, out_cmplx: np.ndarray) -> None:
        """
        Converts a byte array to a complex array.
        """
        if in_bytes.size != out_cmplx.size * 2:
            logger.error(f"Incompatible array sizes: in_bytes.size={in_bytes.size}, out_cmplx.size={out_cmplx.size}")
            raise ValueError("Incompatible array sizes")

        out_cmplx.real = self.lut[in_bytes[0::2]]
        out_cmplx.imag = self.lut[in_bytes[1::2]]

def rotate_fs4(in_cmplx: np.ndarray, out_cmplx: np.ndarray) -> None:
    """
    Rotates the complex signal by Fs/4.
    """
    out_cmplx[0::4] = in_cmplx[0::4]
    out_cmplx[1::4] = in_cmplx[1::4] * 1j
    out_cmplx[2::4] = in_cmplx[2::4] * -1
    out_cmplx[3::4] = in_cmplx[3::4] * -1j

def fir9(in_cmplx: np.ndarray, out_cmplx: np.ndarray) -> None:
    """
    A 9-tap FIR filter.
    """
    coeffs = np.array([
        0.017682261285, 0.048171339939, 0.122424706672, 0.197408519126,
        0.228626345955, 0.197408519126, 0.122424706672, 0.048171339939,
        0.017682261285
    ], dtype=np.float64)
    
    result = np.convolve(in_cmplx, coeffs, mode='valid')
    n = out_cmplx.size
    out_cmplx[:] = result[:n]

def discriminate(in_cmplx: np.ndarray, out_float: np.ndarray) -> None:
    """
    An FSK demodulator.
    """
    n = in_cmplx[:-1]
    np_ = in_cmplx[1:]
    
    real_n = n.real
    imag_n = n.imag
    real_np = np_.real
    imag_np = np_.imag
    
    epsilon = 1e-10
    result = (imag_n * real_np - real_n * imag_np) / (real_n**2 + imag_n**2 + epsilon)
    out_float[:len(result)] = result

def quantize(in_float: np.ndarray, out_byte: np.ndarray) -> None:
    """
    Converts the demodulated signal into a stream of bits.
    """
    for i, val in enumerate(in_float):
        out_byte[i] = (struct.unpack('Q', struct.pack('d', val))[0] >> 63)

class PacketConfig:
    def __init__(self, bit_rate: int, symbol_length: int, preamble_symbols: int, packet_symbols: int, preamble: str) -> None:
        self.bit_rate = bit_rate
        self.symbol_length = symbol_length
        self.preamble_symbols = preamble_symbols
        self.packet_symbols = packet_symbols
        self.preamble = preamble
        self.preamble_bytes = np.array([int(b) for b in preamble], dtype=np.uint8)
        self.preamble_str = self.preamble_bytes.tobytes()
        self.sample_rate = self.bit_rate * self.symbol_length
        self.block_size = 512
        self.block_size2 = self.block_size * 2
        self.preamble_length = self.preamble_symbols * self.symbol_length
        self.packet_length = self.packet_symbols * self.symbol_length
        self.buffer_length = (self.packet_length // self.block_size + 2) * self.block_size

class Demodulator:
    def __init__(self, cfg: PacketConfig) -> None:
        self.cfg = cfg
        self.raw_samples = np.zeros(self.cfg.buffer_length, dtype=np.complex128)
        self.iq = np.zeros(self.cfg.block_size + 9, dtype=np.complex128)
        self.filtered = np.zeros(self.cfg.block_size + 1, dtype=np.complex128)
        self.discriminated = np.zeros(self.cfg.block_size * 2, dtype=np.float64)
        self.quantized = np.zeros(self.cfg.buffer_length, dtype=np.uint8)
        self.pkt = np.zeros((self.cfg.packet_symbols + 7) // 8, dtype=np.uint8)
        self.byte_to_cmplx = ByteToCmplxLUT()

    def demodulate(self, input_data: np.ndarray) -> List[Packet]:
        self.raw_samples = np.roll(self.raw_samples, -self.cfg.block_size)
        
        dest = self.raw_samples[self.cfg.buffer_length - self.cfg.block_size:]
        
        if np.iscomplexobj(input_data):
            if input_data.size != dest.size:
                logger.error(f"Incompatible array sizes: input_data.size={input_data.size}, dest.size={dest.size}")
                raise ValueError("Incompatible array sizes")
            dest[:] = input_data
        else:
            self.byte_to_cmplx.execute(input_data, dest)

        self.iq = np.roll(self.iq, -self.cfg.block_size)
        self.filtered = np.roll(self.filtered, -self.cfg.block_size)
        self.discriminated = np.roll(self.discriminated, -self.cfg.block_size)
        self.quantized = np.roll(self.quantized, -self.cfg.block_size)

        self.iq[9:] = self.raw_samples[self.cfg.buffer_length - self.cfg.block_size:]
        rotate_fs4(self.iq[9:], self.iq[9:])
        fir9(self.iq, self.filtered[1:])
        discriminate(self.filtered, self.discriminated[self.cfg.block_size:])
        quantize(self.discriminated[self.cfg.block_size:], self.quantized[self.cfg.buffer_length - self.cfg.block_size:])
        
        indices = self._search()
        return self._slice(indices)

    def _search(self) -> List[int]:
        indices = []
        preamble_str = self.cfg.preamble_str
        
        for offset in range(self.cfg.symbol_length):
            view = self.quantized[offset::self.cfg.symbol_length]
            view_str = view.tobytes()
            
            start = 0
            while True:
                idx = view_str.find(preamble_str, start)
                if idx == -1:
                    break
                logger.debug("Preamble found at index %d (offset %d)", idx, offset)
                indices.append(idx * self.cfg.symbol_length + offset)
                start = idx + 1
                
        return indices

    def _slice(self, indices: List[int]) -> List[Packet]:
        seen = set()
        packets = []
        for q_idx in indices:
            if q_idx > self.cfg.block_size:
                continue
            
            pkt = bytearray((self.cfg.packet_symbols + 7) // 8)
            for i in range(self.cfg.packet_symbols):
                pkt[i >> 3] <<= 1
                pkt[i >> 3] |= self.quantized[q_idx + (i * self.cfg.symbol_length)]
            
            pkt_bytes = bytes(pkt)
            if pkt_bytes not in seen:
                logger.debug("Sliced packet: %s", pkt_bytes.hex())
                seen.add(pkt_bytes)
                
                # Calculate RSSI and SNR
                signal_start = q_idx
                signal_end = q_idx + self.cfg.packet_length
                
                # Use filtered IQ data for power calculations
                signal_iq = self.filtered[signal_start:signal_end]
                
                # Estimate noise power from a region before the preamble
                noise_start = max(0, signal_start - self.cfg.preamble_length)
                noise_end = signal_start
                if noise_end > noise_start:
                    noise_iq = self.filtered[noise_start:noise_end]
                    noise_power = np.mean(np.abs(noise_iq)**2)
                else:
                    noise_power = 1e-9 # Avoid division by zero if no noise region is available
                
                # Estimate signal power from the preamble region
                preamble_iq = self.filtered[signal_start : signal_start + self.cfg.preamble_length]
                signal_power = np.mean(np.abs(preamble_iq)**2)

                rssi = 10 * math.log10(signal_power) if signal_power > 0 else -120
                snr = 10 * math.log10(signal_power / noise_power) if noise_power > 0 else 50
                
                packets.append(Packet(index=q_idx, data=np.frombuffer(pkt_bytes, dtype=np.uint8), rssi=rssi, snr=snr))
        return packets

    def reset(self) -> None:
        self.raw_samples.fill(0)
        self.iq.fill(0)
        self.filtered.fill(0)
        self.discriminated.fill(0)
        self.quantized.fill(0)
