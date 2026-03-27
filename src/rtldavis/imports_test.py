"""
Smoke tests that verify critical third-party imports succeed.
These catch compatibility breaks (e.g. pkg_resources disappearing from a new
setuptools release) before they reach the device.
"""
import unittest


class TestCriticalImports(unittest.TestCase):
    def test_rtlsdr_importable(self):
        # pyrtlsdr uses pkg_resources at import time; this catches setuptools
        # version incompatibilities that would silently pass all other tests.
        try:
            import rtlsdr  # noqa: F401
        except OSError:
            # librtlsdr.so not present in the test environment — that's fine.
            # We only care that the Python-level import machinery succeeds.
            pass


if __name__ == "__main__":
    unittest.main()
