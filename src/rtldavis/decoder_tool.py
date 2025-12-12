import argparse

def decode_brute_force(hex_data, target_value):
    """
    Tries various decoding patterns on a raw hex data string to find a target value.
    """
    data = bytes.fromhex(hex_data)
    print(f"--- Analyzing frame: {hex_data} for target: {target_value} ---\n")

    found = False

    # Try different byte positions
    for i in range(len(data) - 1):
        # 16-bit value from bytes i and i+1
        val_16bit = (data[i] << 8) | data[i+1]

        # Try different masks (10-bit, 12-bit, 15-bit, 16-bit)
        for mask_bits in [10, 12, 15, 16]:
            mask = (1 << mask_bits) - 1
            masked_val = val_16bit & mask

            # Try different scaling factors
            for scale in [1.0, 10.0, 100.0]:
                scaled_val = masked_val / scale

                # Check direct match
                if abs(scaled_val - target_value) < 0.1:
                    print(f"SUCCESS: Found match!")
                    print(f"  - Bytes: data[{i}] and data[{i+1}] ({data[i]:02x} {data[i+1]:02x})")
                    print(f"  - Logic: ((data[{i}] << 8) | data[{i+1}]) & 0x{mask:X}")
                    print(f"  - Raw value: {masked_val}")
                    print(f"  - Scale: / {scale}")
                    print(f"  - Result: {scaled_val:.1f}\n")
                    found = True

                # Check with offset
                for offset in [-40.0, -90.0]:
                    offset_val = scaled_val + offset
                    if abs(offset_val - target_value) < 0.1:
                        print(f"SUCCESS: Found match with offset!")
                        print(f"  - Bytes: data[{i}] and data[{i+1}] ({data[i]:02x} {data[i+1]:02x})")
                        print(f"  - Logic: (((data[{i}] << 8) | data[{i+1}]) & 0x{mask:X}) / {scale}) + {offset}")
                        print(f"  - Raw value: {masked_val}")
                        print(f"  - Result: {offset_val:.1f}\n")
                        found = True

    # Try single bytes
    for i in range(len(data)):
        val_8bit = data[i]
        if abs(val_8bit - target_value) < 0.1:
            print(f"SUCCESS: Found match (8-bit)!")
            print(f"  - Byte: data[{i}] ({data[i]:02x})")
            print(f"  - Logic: data[{i}]")
            print(f"  - Result: {val_8bit}\n")
            found = True

    if not found:
        print("No simple decoding pattern found.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Brute-force decoder for Davis sensor data.")
    parser.add_argument("hex_data", help="Raw sensor data frame in hexadecimal.")
    parser.add_argument("target_value", type=float, help="The expected decoded value (e.g., 74.6 for humidity).")
    args = parser.parse_args()

    decode_brute_force(args.hex_data, args.target_value)
