"""
Decoder for Davis humidity data.
"""

def decode_humidity(data: bytes) -> float:
    """
    Decodes humidity from a raw data packet.

    From https://github.com/dekay/DavisRFM69/wiki/Message-Protocol:
    > Humidity is represented as two bytes in Byte 3 and Byte 4 as a ten bit
    > value. Bits 5 and 4 in Byte 4 are the two most significant bits. Byte 3
    > is the low order byte. The ten bit value is then 10x the humidity value
    > displayed on the console.
    >
    > humidity = (((Byte4 >> 4) << 8) + Byte3) / 10.0
    >
    > Here is an example using an actual message from my console.
    > a0 06 52 83 38 00 5a c8
    > The corresponding humidity value is then
    > ((0x38 >> 4) << 8) + 0x83 = 131 + 768 = 899 = 89.9% Relative Humidity
    """
    # The documentation seems to have a typo.
    # ((0x38 >> 4) << 8) is (3 << 8) = 768.
    # 0x83 is 131.
    # 768 + 131 = 899.
    # So the logic is correct, even if the text description is slightly confusing.
    
    raw_humidity = ((data[4] >> 4) << 8) + data[3]
    humidity = float(raw_humidity) / 10.0
    return humidity
