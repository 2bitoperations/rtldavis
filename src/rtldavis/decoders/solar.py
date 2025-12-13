"""
Decoder for Davis solar radiation data.
"""
import logging

def decode_solar(data: bytes, logger: logging.Logger) -> float:
    """
    Decodes solar radiation from a raw data packet.

    The decoding logic is based on the analysis in this forum post:
    https://www.wxforum.net/index.php?topic=27244.0

    The formula is derived from empirical data and is more accurate than
    the simple multiplication factor used in some other implementations.

    w/m^2 = round(((VALUE >> 4) - 4) / 2.27)
    where VALUE is the 16-bit value from Bytes 3 and 4.
    """
    if data[3] == 0xFF:
        logger.info("    - No solar sensor detected")
        return 0.0

    raw_value = (data[3] << 8) + data[4]
    
    # The lower nibble of Byte4 is not used
    value_shifted = raw_value >> 4
    
    # The '0' value is represented by 4
    if value_shifted <= 4:
        return 0.0

    solar_rad = round(((value_shifted) - 4) / 2.27)
    
    log_msg = f"    - Raw 16-bit Value: 0x{raw_value:04X}\n"
    log_msg += f"    - Value >> 4: 0x{value_shifted:03X} ({value_shifted})\n"
    log_msg += f"    - Formula: round(((VALUE >> 4) - 4) / 2.27)\n"
    log_msg += f"    - Solar Radiation: {solar_rad:.1f} W/m^2"
    logger.info(log_msg)

    return float(solar_rad)
