from rtlsdr.rtlsdr import RtlSdr
import inspect

print("Static methods of RtlSdr:")
for name, member in inspect.getmembers(RtlSdr):
    if name.startswith('get_device'):
        print(f"{name}: {member}")

print("\nTrying to call them:")
try:
    count = RtlSdr.get_device_count()
    print(f"Device count: {count}")
    
    for i in range(count):
        print(f"\nDevice {i}:")
        try:
            print(f"  Name: {RtlSdr.get_device_name(i)}")
        except Exception as e:
            print(f"  Name error: {e}")
            
        try:
            print(f"  Manufacturer: {RtlSdr.get_device_manufacturer(i)}")
        except Exception as e:
            print(f"  Manufacturer error: {e}")
            
        try:
            print(f"  Product: {RtlSdr.get_device_product(i)}")
        except Exception as e:
            print(f"  Product error: {e}")

        try:
            print(f"  Serial: {RtlSdr.get_device_serial_addresses()[i]}")
        except Exception as e:
            print(f"  Serial error: {e}")

except Exception as e:
    print(f"Error: {e}")
