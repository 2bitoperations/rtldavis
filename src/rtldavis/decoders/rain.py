"""
Decoder for Davis rain total data.
"""

def decode_rain_total(data: bytes) -> float:
    """
    Decodes the cumulative rain total from a raw data packet.

    From https://github.com/dekay/DavisRFM69/wiki/Message-Protocol:
    > Message e:
    > Rain is in Byte 3. It is a running total of bucket tips that wraps
    > back around to 0 eventually from the ISS. It is up to the console
    > to keep track of changes in this byte. Only bits 0 through 6 of
    > byte 3 are used, so the counter will overflow after 0x7F (127).
    """
    rain_clicks = data[3] & 0x7F
    return float(rain_clicks)
