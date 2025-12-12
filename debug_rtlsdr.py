import rtlsdr
import inspect
import sys

print(f"rtlsdr package: {rtlsdr}")
print(f"dir(rtlsdr): {dir(rtlsdr)}")

try:
    from rtlsdr import RtlSdr
    print(f"\nRtlSdr class: {RtlSdr}")
    print(f"dir(RtlSdr): {dir(RtlSdr)}")
    
    # Check for librtlsdr wrapper
    if hasattr(rtlsdr, 'librtlsdr'):
        print(f"\nrtlsdr.librtlsdr: {rtlsdr.librtlsdr}")
        print(f"dir(rtlsdr.librtlsdr): {dir(rtlsdr.librtlsdr)}")

except ImportError as e:
    print(f"ImportError: {e}")

try:
    import rtlsdr.rtlsdr
    print(f"\nrtlsdr.rtlsdr module: {rtlsdr.rtlsdr}")
    print(f"dir(rtlsdr.rtlsdr): {dir(rtlsdr.rtlsdr)}")
except ImportError as e:
    print(f"ImportError for rtlsdr.rtlsdr: {e}")
