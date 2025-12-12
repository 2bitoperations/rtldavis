"""
Decoder for Davis rain rate data.
"""
import logging

def decode_rain_rate(data: bytes, logger: logging.Logger) -> float:
    """
    Decodes rain rate from a raw data packet.

    The decoding logic is based on the Davis RFM69 message protocol documentation:
    https://github.com/dekay/DavisRFM69/wiki/Message-Protocol

    The rain rate is calculated from the time between bucket tips.
    A bucket tip corresponds to 0.01" of rain for US models.

    The raw packet contains a 10-bit value representing a base time interval.
    - Byte3 contains the lower 8 bits.
    - Bits 4 and 5 of Byte4 contain the upper 2 bits.

    The packet also indicates "light" or "strong" rain, which determines how
    the base time interval is interpreted.
    - Light rain: time_between_clicks = base_time
    - Strong rain: time_between_clicks = base_time / 16

    The rain rate in inches per hour is then calculated as:
    inches_per_hour = (3600 seconds/hour) / time_between_clicks_s * (0.01 inches/click)
                    = 36 / time_between_clicks_s
    """
    # Byte 3 is the low 8 bits of the time value.
    # Byte 4 bits 4 & 5 are the high 2 bits.
    # raw_val is a 10-bit number representing the base time interval.
    raw_val = (((data[4] & 0x30) >> 4) * 256) + data[3]
    
    log_msg = f"    - Raw time value: {raw_val}\n"

    if data[3] == 0xFF:
        log_msg += "    - No rain detected (Byte3 == 0xFF)"
        logger.info(log_msg)
        return 0.0

    if raw_val == 0:
        log_msg += "    - No rain detected (raw time value is 0)"
        logger.info(log_msg)
        return 0.0

    # Bit 6 of Byte4 indicates light or strong rain.
    is_strong_rain = (data[4] & 0x40) != 0
    rain_type = "Strong" if is_strong_rain else "Light"
    log_msg += f"    - Rain Type: {rain_type}\n"

    if is_strong_rain:
        # For strong rain, the time between clicks is divided by 16.
        time_between_clicks = float(raw_val) / 16.0
    else:
        # For light rain, the time is the raw value.
        time_between_clicks = float(raw_val)

    log_msg += f"    - Time between clicks: {time_between_clicks:.4f} s\n"

    # inches_per_hour = 36 / time_between_clicks
    inches_per_hour = 36.0 / time_between_clicks

    log_msg += f"    - Rain Rate: {inches_per_hour:.3f} in/hr"
    logger.info(log_msg)
    
    return inches_per_hour
