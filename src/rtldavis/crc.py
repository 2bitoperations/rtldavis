import numpy as np


class CRC:
    """
    A class for calculating CRC-16-CCITT checksums.
    """

    def __init__(self, name: str, init: int, poly: int, residue: int) -> None:
        self.name: str = name
        self.init: np.uint16 = np.uint16(init)
        self.poly: np.uint16 = np.uint16(poly)
        self.residue: np.uint16 = np.uint16(residue)
        self.tbl: np.ndarray = self._new_table(self.poly)

    def __str__(self) -> str:
        return f"{{Name:{self.name} Init:0x{self.init:04X} Poly:0x{self.poly:04X} Residue:0x{self.residue:04X}}}"

    def checksum(self, data: bytes) -> np.uint16:
        """
        Calculates the CRC-16-CCITT checksum for the given data.
        """
        crc: np.uint16 = self.init
        for byte in data:
            crc = (crc << 8) ^ self.tbl[(crc >> 8) ^ byte]
        return crc

    @staticmethod
    def _new_table(poly: np.uint16) -> np.ndarray:
        """
        Creates a new CRC table.
        """
        table = np.zeros(256, dtype=np.uint16)
        for i in range(256):
            crc = np.uint16(i) << 8
            for _ in range(8):
                if crc & 0x8000:
                    crc = (crc << 1) ^ poly
                else:
                    crc <<= 1
            table[i] = crc
        return table
