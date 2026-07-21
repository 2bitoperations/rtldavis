from rtldavis.mqtt import _aggregate, _circular_mean_deg


def test_average_is_default_for_plain_measurements():
    assert _aggregate("temperature", [20.0, 22.0]) == 21.0


def test_wind_gust_takes_max_not_average():
    assert _aggregate("wind_gust_speed", [10.0, 40.0, 15.0]) == 40.0


def test_cumulative_counters_take_last_value():
    assert _aggregate("rain_total_raw", [1.0, 1.5, 2.0]) == 2.0
    assert _aggregate("rain_total_hourly", [0.0, 0.01]) == 0.01
    assert _aggregate("seconds_since_last_data", [1, 2, 3]) == 3


def test_wind_direction_uses_circular_mean():
    # Naive averaging of 350 and 10 gives 180 (due south) - dead wrong for a
    # reading that's actually hovering around due north (0/360).
    assert _aggregate("wind_direction", [350, 10]) == 0


def test_circular_mean_handles_wrap_around():
    assert _circular_mean_deg([359, 1]) == 0
    assert _circular_mean_deg([90, 90, 90]) == 90
