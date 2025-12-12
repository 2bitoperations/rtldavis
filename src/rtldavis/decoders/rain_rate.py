"""
Decoder for Davis rain rate data.
"""
import logging

def decode_rain_rate(data: bytes, logger: logging.Logger) -> float:
    """
    Decodes rain rate from a raw data packet.

    From https://github.com/dekay/DavisRFM69/wiki/Message-Protocol and rtldavis2.
    """
    if data[3] == 0xFF:
        logger.info("    - No rain detected (Byte3 == 0xFF)")
        return 0.0

    raw_val = ((data[4] & 0x30) << 4) + data[3]
    
    if raw_val == 0:
        logger.info("    - No rain detected (raw value is 0)")
        return 0.0

    clicks_per_hour = 0.0
    rain_type = "Unknown"
    if (data[4] & 0x40) == 0: # Light rain
        rain_type = "Light"
        clicks_per_hour = 576000.0 / float(raw_val)
    else: # Strong rain
        rain_type = "Strong"
        clicks_per_hour = 3600.0 / float(raw_val)
        
    # Convert to inches per hour (assuming 0.01 inch bucket)
    inches_per_hour = clicks_per_hour * 0.01
    
    log_msg = f"    - Raw Value: 0x{raw_val:04X}\n"
    log_msg += f"    - Rain Type: {rain_type}\n"
    log_msg += f"    - Clicks/hr: {clicks_per_hour:.2f}\n"
    log_msg += f"    - Rain Rate: {inches_per_hour:.3f} in/hr"
    logger.info(log_msg)
    
    return inches_per_hour
