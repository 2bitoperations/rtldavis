"""
Decoder for Davis UV index data.
"""
import logging

def decode_uv(data: bytes, logger: logging.Logger) -> float:
    """
    Decodes the UV index from a raw data packet.

    From https://github.com/dekay/DavisRFM69/wiki/Message-Protocol:
    > Message 4: UV Index
    > Bytes 3 and 4 are for UV Index. The first byte is MSB and the second LSB.
    > A value of FF in the third byte indicates that no sensor is present.
    >
    > UVIndex = ((Byte3 << 8) + Byte4) >> 6) / 50.0
    """
    if data[3] == 0xFF:
        logger.info("    - No UV sensor detected")
        return 0.0

    raw_uv = ((data[3] << 8) + data[4]) >> 6
    uv_index = float(raw_uv) / 50.0
    
    log_msg = f"    - Raw Value: 0x{raw_uv:03X} ({raw_uv})\n"
    log_msg += f"    - Formula: (((Byte3 << 8) + Byte4) >> 6) / 50.0\n"
    log_msg += f"    - UV Index: {uv_index:.1f}"
    logger.info(log_msg)

    return uv_index
