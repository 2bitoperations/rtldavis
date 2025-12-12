"""
Decoder for Davis solar radiation data.
"""

def decode_solar(data: bytes) -> float:
    """
    Decodes solar radiation from a raw data packet.

    From https://github.com/dekay/DavisRFM69/wiki/Message-Protocol:
    > Message 6: Solar Radiation
    > Bytes 3 and 4 are solar radiation. The first byte is MSB and the
    > second LSB. The lower nibble of the 4th byte is again always 5, so
    > they only use the first three nibbles. A value of FF in the third
    > byte indicates that no sensor is present.
    >
    > Solar radiation = (((Byte3 << 8) + Byte4) >> 6) * 1.757936
    """
    if data[3] == 0xFF:
        return 0.0 # No sensor

    raw_solar = ((data[3] << 8) + data[4]) >> 6
    solar_rad = float(raw_solar) * 1.757936
    return solar_rad
