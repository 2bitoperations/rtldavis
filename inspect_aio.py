import rtlsdr
import inspect

print(f"rtlsdr dir: {dir(rtlsdr)}")

try:
    from rtlsdr import RtlSdrAio
    print("RtlSdrAio found in rtlsdr")
    print(f"RtlSdrAio dir: {dir(RtlSdrAio)}")
except ImportError:
    print("RtlSdrAio NOT found in rtlsdr")

try:
    import rtlsdr.rtlsdraio
    print("rtlsdr.rtlsdraio module found")
    print(f"rtlsdr.rtlsdraio dir: {dir(rtlsdr.rtlsdraio)}")
except ImportError:
    print("rtlsdr.rtlsdraio module NOT found")
