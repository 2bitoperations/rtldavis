"""
Decoder for Davis supercap voltage data.
"""

def decode_supercap(data: bytes) -> float:
    """
    Decodes the supercap voltage from a raw data packet.

    From https://github.com/dekay/DavisRFM69/wiki/Message-Protocol:
    > Message 2: Supercap voltage (Vue only)
    > Bytes 3 and 4 are for reporting the Supercap voltage.
    > voltage = ((Byte3 * 4) + ((Byte4 && 0xC0) / 64)) / 100

    Note: The C-style `&&` is a logical AND, which is incorrect here.
    The rtldavis2 Go code uses the correct bitwise AND.
    `voltage := float32((m.Data[3]<<2)+((m.Data[4]&0xC0)>>6)) / 100`
    This matches the intent of the documentation.
    """
    raw_voltage = (data[3] << 2) + ((data[4] & 0xC0) >> 6)
    voltage = float(raw_voltage) / 100.0
    return voltage
