"""
Decoder for Davis solar radiation data.
"""
import logging

def decode_solar(data: bytes, logger: logging.Logger) -> float:
    """
    Decodes solar radiation from a raw data packet.

    From https://github.com/dekay/DavisRFM69/wiki/Message-Protocol:
    > Message 6: Solar Radiation
    > Bytes 3 and 4 are solar radiation. The first byte is MSB and the
    > second LSB. A value of FF in the third byte indicates that no sensor
    > is present.
    >
    > Solar radiation = (((Byte3 << 8) + Byte4) >> 6) * 1.757936
    """
    if data[3] == 0xFF:
        logger.info("    - No solar sensor detected")
        return 0.0

    raw_solar = ((data[3] << 8) + data[4]) >> 6
    solar_rad = float(raw_solar) * 1.757936
    
    log_msg = f"    - Raw Value: 0x{raw_solar:03X} ({raw_solar})\n"
    log_msg += f"    - Formula: (((Byte3 << 8) + Byte4) >> 6) * 1.757936\n"
    log_msg += f"    - Solar Radiation: {solar_rad:.1f} W/m^2"
    logger.info(log_msg)

    return solar_rad
