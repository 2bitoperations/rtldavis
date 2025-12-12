"""
Decoder for Davis humidity data.
"""
import logging

def decode_humidity(data: bytes, logger: logging.Logger) -> float:
    """
    Decodes humidity from a raw data packet.

    From https://github.com/dekay/DavisRFM69/wiki/Message-Protocol:
    > Humidity is represented as two bytes in Byte 3 and Byte 4 as a ten bit
    > value. Bits 5 and 4 in Byte 4 are the two most significant bits. Byte 3
    > is the low order byte. The ten bit value is then 10x the humidity value
    > displayed on the console.
    >
    > humidity = (((Byte4 >> 4) << 8) + Byte3) / 10.0
    """
    raw_humidity = ((data[4] >> 4) << 8) + data[3]
    humidity = float(raw_humidity) / 10.0
    
    log_msg = f"    - Raw Value: 0x{raw_humidity:03X} ({raw_humidity})\n"
    log_msg += f"    - Formula: ((((Byte4 >> 4) << 8) + Byte3) / 10.0)\n"
    log_msg += f"    - Humidity: {humidity:.1f}%"
    logger.info(log_msg)

    return humidity
