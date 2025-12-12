import rtlsdr
import sys

print(f"rtlsdr: {dir(rtlsdr)}")

try:
    from rtlsdr import rtlsdr as inner_rtlsdr
    print(f"rtlsdr.rtlsdr: {dir(inner_rtlsdr)}")
except ImportError:
    print("Could not import rtlsdr.rtlsdr")

try:
    from rtlsdr import librtlsdr
    print(f"rtlsdr.librtlsdr: {dir(librtlsdr)}")
    if hasattr(librtlsdr, 'librtlsdr'):
        print(f"rtlsdr.librtlsdr.librtlsdr: {dir(librtlsdr.librtlsdr)}")
except ImportError:
    print("Could not import rtlsdr.librtlsdr")
