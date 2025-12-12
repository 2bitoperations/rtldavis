"""
Decoder for Davis rain total data.
"""
import logging

def decode_rain_total(data: bytes, logger: logging.Logger) -> float:
    """
    Decodes the cumulative rain total from a raw data packet.

    From https://github.com/dekay/DavisRFM69/wiki/Message-Protocol:
    > Message e:
    > Rain is in Byte 3. It is a running total of bucket tips that wraps
    > back around to 0 eventually from the ISS. It is up to the console
    > to keep track of changes in this byte. Only bits 0 through 6 of
    > byte 3 are used, so the counter will overflow after 0x7F (127).
    """
    rain_clicks = data[3] & 0x7F
    
    log_msg = f"    - Raw Value (Byte3 & 0x7F): {rain_clicks}\n"
    log_msg += f"    - Rain Total: {rain_clicks} clicks"
    logger.info(log_msg)

    return float(rain_clicks)
