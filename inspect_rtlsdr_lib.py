import rtlsdr.rtlsdr
import inspect

print("Functions in rtlsdr.rtlsdr module:")
for name, member in inspect.getmembers(rtlsdr.rtlsdr):
    if name.startswith('get_device') or name == 'librtlsdr':
        print(f"{name}: {member}")

print("\nAttributes of RtlSdr class:")
for name, member in inspect.getmembers(rtlsdr.rtlsdr.RtlSdr):
    if name.startswith('get_device'):
        print(f"{name}: {member}")
