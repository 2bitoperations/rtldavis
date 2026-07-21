from rtldavis import protocol

def test_swap_bit_order():
    """
    Test the bit reversal function used to convert between LSB-first Davis FSK
    and the MSB-first decoding formats.
    """
    assert protocol.swap_bit_order(0x00) == 0x00
    assert protocol.swap_bit_order(0xFF) == 0xFF
    assert protocol.swap_bit_order(0x01) == 0x80  # 00000001 -> 10000000
    assert protocol.swap_bit_order(0x80) == 0x01
    assert protocol.swap_bit_order(0x55) == 0xAA  # 01010101 -> 10101010
    assert protocol.swap_bit_order(0xAA) == 0x55

def test_crc_check():
    """
    Test the CRC functionality to ensure valid packets pass.
    """
    from rtldavis.crc import CRC
    crc = CRC("CCITT-16", 0, 0x1021, 0)

    # Valid payload from a real rain packet:
    # 0xCB 0x89 is the sync word. The next 8 bytes are the payload + CRC.
    # Payload bytes: 07 C0 2B 0B 80 40
    # CRC bytes: 8E FF
    # Over-the-air bytes are LSB-first; the real decode path bit-swaps each
    # byte (see protocol.swap_bit_order / Parser.parse) before checksumming,
    # so the test does the same.
    payload = bytes([0x07, 0xC0, 0x2B, 0x0B, 0x80, 0x40, 0x8E, 0xFF])
    swapped = bytes(protocol.swap_bit_order(b) for b in payload)

    assert crc.checksum(swapped) == 0, "Valid packet should compute a 0 checksum"

    bad_payload = bytes([0x07, 0xC0, 0x2B, 0x0B, 0x80, 0x40, 0x8E, 0xFE])
    bad_swapped = bytes(protocol.swap_bit_order(b) for b in bad_payload)
    assert crc.checksum(bad_swapped) != 0, "Invalid packet should fail checksum"
