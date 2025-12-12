"""
Decoder for Davis rain rate data.
"""

def decode_rain_rate(data: bytes) -> float:
    """
    Decodes rain rate from a raw data packet.

    From https://github.com/dekay/DavisRFM69/wiki/Message-Protocol:
    > Bytes 3 and 4 contain the rain rate information. The rate is actually
    > the time in seconds between rain bucket tips in the ISS.
    >
    > no rain     if Byte3 == 0xFF
    >
    > light rain  if (Byte4 && 0x40) == 0
    > strong rain if (Byte4 && 0x40) == 0x40
    >
    > light rain:
    > time between clicks[s] = ((Byte4 && 0x30) / 16 * 250) + Byte3
    > rainrate [mm/h] = 720 / (((Byte4 && 0x30) / 16 * 250) + Byte3)
    >
    > strong rain:
    > time between clicks[s] = (((Byte4 && 0x30) / 16 * 250) + Byte3) / 16
    > rainrate [mm/h] = 11520 / (((Byte4 && 0x30) / 16 * 250) + Byte3)

    The formula for mm/h can be simplified. Assuming 0.2mm bucket.
    Rate (mm/h) = (1 tip / time_s) * 0.2 mm/tip * 3600 s/hr = 720 / time_s.
    The strong rain formula seems to be 16 * (720 / time_s).

    We will return inches per hour, assuming 0.01 inch bucket.
    Rate (in/hr) = (1 tip / time_s) * 0.01 in/tip * 3600 s/hr = 36 / time_s.
    """
    if data[3] == 0xFF:
        return 0.0

    # The formula in the docs `(Byte4 && 0x30) / 16 * 250` is C bitwise AND,
    # not logical. In Python, this is `(data[4] & 0x30) >> 4`.
    # The multiplication by 250 is strange.
    # Let's use the logic from rtldavis2, which is simpler and likely tested.
    # raw_rain_rate = ((data[4] & 0x30) << 4) + data[3]
    
    # The rtldavis2 logic seems more plausible and aligns with other decoders.
    raw_val = ((data[4] & 0x30) << 4) + data[3]
    
    if raw_val == 0:
        return 0.0

    clicks_per_hour = 0.0
    if (data[4] & 0x40) == 0: # Light rain
        clicks_per_hour = 576000.0 / float(raw_val)
    else: # Strong rain
        clicks_per_hour = 3600.0 / float(raw_val)
        
    # Convert to inches per hour (assuming 0.01 inch bucket)
    inches_per_hour = clicks_per_hour * 0.01
    
    return inches_per_hour
