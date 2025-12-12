"""
Decoder for Davis UV index data.
"""

def decode_uv(data: bytes) -> float:
    """
    Decodes the UV index from a raw data packet.

    From https://github.com/dekay/DavisRFM69/wiki/Message-Protocol:
    > Message 4: UV Index
    > Bytes 3 and 4 are for UV Index. The first byte is MSB and the second LSB.
    > The lower nibble of the 4th byte is always 5, so they only use the first
    > three nibbles. A value of FF in the third byte indicates that no sensor
    > is present.
    >
    > The UV index is calcuated as follows as discussed here and here.
    > UVIndex = ((Byte3 << 8) + Byte4) >> 6) / 50.0
    """
    if data[3] == 0xFF:
        return 0.0 # No sensor

    raw_uv = ((data[3] << 8) + data[4]) >> 6
    uv_index = float(raw_uv) / 50.0
    return uv_index
