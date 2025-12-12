from rtlsdr.rtlsdr import RtlSdr
import inspect

try:
    sdr = RtlSdr(device_index=0)
    print("Attributes of RtlSdr instance:")
    for name in dir(sdr):
        if not name.startswith('__'):
            print(name)
    sdr.close()
except Exception as e:
    print(f"Error: {e}")
