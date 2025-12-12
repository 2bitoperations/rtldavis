"""
Decoder for Davis temperature data.
"""
import logging

def decode_temperature(data: bytes, logger: logging.Logger) -> float:
    """
    Decodes temperature from a raw data packet.

    From https://github.com/dekay/DavisRFM69/wiki/Message-Protocol:
    > Byte 3 and 4 are temperature. The first byte is MSB and the second LSB.
    > The value is signed with 0x0000 representing 0F. This reading in the old
    > version of the ISS was taked from an analog sensor and measured by an A/D.
    > The newer ISS uses a digital sensor but still represents the data in the
    > same way. 160 counts (0xa0) represents 1 degree F. A message of
    > 80 04 70 0f 99 00 91 11
    > represents temperature as 0x0f99, or 3993 decimal. Divide 3993 by 160
    > to get the console reading of 25.0F
    >
    > tempF = ((Byte3 * 256 + Byte4) / 160
    """
    raw_temp = (data[3] << 8) | data[4]
    temp_f = float(raw_temp) / 160.0
    
    log_msg = f"    - Raw Value: 0x{raw_temp:04X} ({raw_temp})\n"
    log_msg += f"    - Formula: {raw_temp} / 160.0\n"
    log_msg += f"    - Temperature: {temp_f:.1f}°F"
    logger.info(log_msg)

    return temp_f
