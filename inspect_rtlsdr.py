from rtlsdr.rtlsdr import RtlSdr
import inspect

print("Methods of RtlSdr:")
for name, data in inspect.getmembers(RtlSdr):
    if name.startswith('get_device'):
        print(name)
