"""
Decoder for Davis supercap voltage data.
"""
import logging

def decode_supercap(data: bytes, logger: logging.Logger) -> float:
    """
    Decodes the supercap voltage from a raw data packet.

    From rtldavis2, originally from:
    https://www.carluccio.de/davis-vue-hacking-part-2/
    > Goldcap [v]= ((Byte3 * 4) + ((Byte4 && 0xC0) / 64)) / 100
    
    The rtldavis2 Go code implements this as:
    `voltage := float32((m.Data[3]<<2)+((m.Data[4]&0xC0)>>6)) / 100`
    """
    raw_voltage = (data[3] << 2) + ((data[4] & 0xC0) >> 6)
    voltage = float(raw_voltage) / 100.0
    
    log_msg = f"    - Raw Value: 0x{raw_voltage:03X} ({raw_voltage})\n"
    log_msg += f"    - Formula: ((Byte3 << 2) + ((Byte4 & 0xC0) >> 6)) / 100.0\n"
    log_msg += f"    - Supercap Voltage: {voltage:.2f} V"
    logger.info(log_msg)

    return voltage
