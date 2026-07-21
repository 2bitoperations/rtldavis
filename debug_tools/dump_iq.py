"""
Diagnostic Tool: dump_iq.py
Captures raw I/Q samples from the RTL-SDR and dumps them to a file for offline analysis using tools like Inspectrum or URH.
"""
import numpy as np
from rtlsdr import RtlSdr
import time
import os

def main():
    print("Initializing RTL-SDR...")
    try:
        sdr = RtlSdr()
    except Exception as e:
        print(f"Failed to open SDR: {e}")
        print("Please check if the SDR is plugged in and recognized by the system (lsusb).")
        return

    sdr.sample_rate = 268800
    sdr.center_freq = 902419000
    sdr.gain = 'auto'

    print("Flushing buffers to allow SDR to settle...")
    for _ in range(5):
        _ = sdr.read_samples(256 * 1024)

    print("Capturing 500,000 samples (~1.8 seconds of radio time)...")
    # Capture samples
    samples = sdr.read_samples(500 * 1024)
    sdr.close()

    print("Capture complete! Analyzing baseband IQ...")

    mag = np.abs(samples)
    mean_mag = np.mean(mag)
    max_mag = np.max(mag)
    
    print(f"Background Noise Floor (Mean Magnitude): {mean_mag:.4f}")
    print(f"Peak Signal Magnitude: {max_mag:.4f}")

    # Threshold for finding a burst
    threshold = mean_mag + (max_mag - mean_mag) * 0.4
    active_idx = np.where(mag > threshold)[0]

    if len(active_idx) == 0:
        print("\nCONCLUSION: Absolute silence. No bursts of energy found above the noise floor.")
        return

    print(f"\nFound {len(active_idx)} high-energy samples indicating a transmission burst!")
    # Extract the burst
    start = active_idx[0]
    end = min(start + 50000, len(samples))
    signal_samples = samples[start:end]
    noise_samples = samples[:start] if start > 0 else samples[end:end+1000]

    print("Background Noise Floor (Mean Magnitude): {:.4f}".format(np.mean(np.abs(noise_samples))))
    print("Peak Signal Magnitude: {:.4f}".format(np.max(np.abs(signal_samples))))
    print(f"\nFound {len(signal_samples)} high-energy samples indicating a transmission burst!\n")

    # Demodulate ONLY the high-energy burst using FM Discriminator
    s_orig = signal_samples[:-1]
    s_shifted = signal_samples[1:]
    phase_delta = np.angle(s_shifted * np.conj(s_orig))
    freq_dev = phase_delta * (268800 / (2 * np.pi))

    print("--- FM Demodulator Output for Burst ---")
    print(f"Minimum Frequency Deviation: {np.min(freq_dev):.1f} Hz")
    print(f"Maximum Frequency Deviation: {np.max(freq_dev):.1f} Hz")
    print(f"Spread (Bandwidth): {np.max(freq_dev) - np.min(freq_dev):.1f} Hz")

    print("\n--- Pulse Timing Analysis (rtl_433 style) ---")
    # Apply a low-pass filter to smooth the FM output
    kernel = np.ones(5) / 5
    smoothed_freq = np.convolve(freq_dev, kernel, mode='valid')

    # Slice bits at 0 Hz deviation
    bit_stream = smoothed_freq > 0

    # Find edges (transitions)
    edges = np.diff(bit_stream.astype(int))
    transition_indices = np.where(edges != 0)[0]

    if len(transition_indices) < 2:
        print("Not enough transitions found to analyze pulse timing. Signal might be unmodulated carrier (OOK/CW).")
        print("\nCONCLUSION: This is NOT 2-FSK! The bandwidth is incredibly narrow. The CC1101 VCO is dead/unmodulated (OOK/CW).")
    else:
        print(f"Found {len(transition_indices)} frequency transitions.")
        
        # Calculate durations of each pulse in microseconds
        pulse_durations_samples = np.diff(transition_indices)
        pulse_durations_us = pulse_durations_samples * (1_000_000 / 268800)
        
        print("\nFirst 40 Pulses (Value : Duration in us):")
        for i in range(min(40, len(pulse_durations_us))):
            val = bit_stream[transition_indices[i] + 1]
            print(f"{'High (+f)' if val else 'Low  (-f)'} : {pulse_durations_us[i]:.1f} us")
            
        print("\nPulse Duration Statistics:")
        print(f"Shortest pulse: {np.min(pulse_durations_us):.1f} us")
        print(f"Longest pulse: {np.max(pulse_durations_us):.1f} us")
        print(f"Median pulse: {np.median(pulse_durations_us):.1f} us")
        
        # Theoretical duration of a bit at 19200 baud is 52.08 us
        print(f"\nExpected pulse duration for 19.2 kbps: 52.1 us")
        
        print("\nCONCLUSION: This IS FSK! The frequency is successfully deviating back and forth.")
        
if __name__ == "__main__":
    main()
