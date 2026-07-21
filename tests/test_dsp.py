import numpy as np
from rtldavis import dsp

def test_quantize_polarity():
    """
    Test that negative values map to 1 and positive values map to 0.
    This was the cause of the major FSK polarity regression.
    """
    in_float = np.array([-5.0, 5.0, -0.1, 0.1, 0.0])
    out_byte = np.zeros(len(in_float), dtype=np.uint8)
    
    dsp.quantize(in_float, out_byte)
    
    # Negative should be 1, positive should be 0, zero can be 0.
    assert out_byte[0] == 1, "Negative value should be 1"
    assert out_byte[1] == 0, "Positive value should be 0"
    assert out_byte[2] == 1, "Small negative value should be 1"
    assert out_byte[3] == 0, "Small positive value should be 0"
    assert out_byte[4] == 0, "Zero should be 0"

def test_quantize_large_arrays():
    """
    Test the quantizer over a larger array of random floats.
    """
    rng = np.random.default_rng(42)
    in_float = rng.uniform(-10, 10, 1000)
    out_byte = np.zeros(len(in_float), dtype=np.uint8)
    
    dsp.quantize(in_float, out_byte)
    
    for val, byte in zip(in_float, out_byte):
        expected = 1 if val < 0 else 0
        assert byte == expected
