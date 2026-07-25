import time
import unittest
from types import SimpleNamespace

from .sensor_store import SensorStore
from .weatherlink import WindRollingWindow, build_current_conditions, dew_point_f


def _msg(**sensor_values):
    return SimpleNamespace(sensor_values=sensor_values)


class TestDewPoint(unittest.TestCase):
    def test_known_reference_point(self):
        # 68F / 50% RH -> ~48.7F, a standard reference value.
        self.assertAlmostEqual(dew_point_f(68.0, 50.0), 48.7, delta=0.2)

    def test_saturated_air_dew_point_equals_temp(self):
        self.assertAlmostEqual(dew_point_f(70.0, 100.0), 70.0, delta=0.2)


class TestWindRollingWindow(unittest.TestCase):
    def setUp(self):
        self.window = WindRollingWindow()

    def test_no_samples_has_no_last_sample_time(self):
        self.assertIsNone(self.window.seconds_since_last_sample())

    def test_avg_matches_manual_mean(self):
        self.window.record(10.0, 100, timestamp=0)
        self.window.record(20.0, 110, timestamp=30)
        self.window.record(30.0, 120, timestamp=60)
        self.assertAlmostEqual(self.window.avg_kmh(120, now=60), 20.0, delta=0.001)

    def test_hi_returns_max_speed_and_its_direction(self):
        self.window.record(10.0, 100, timestamp=0)
        self.window.record(45.0, 270, timestamp=30)
        self.window.record(20.0, 120, timestamp=60)
        hi_speed, hi_dir = self.window.hi_kmh(600, now=60)
        self.assertAlmostEqual(hi_speed, 45.0, delta=0.001)
        self.assertEqual(hi_dir, 270)

    def test_single_sample_window_returns_that_sample(self):
        self.window.record(15.0, 200, timestamp=0)
        self.assertAlmostEqual(self.window.avg_kmh(120, now=0), 15.0, delta=0.001)

    def test_samples_older_than_max_window_are_pruned(self):
        self.window.record(10.0, timestamp=0)
        self.window.record(20.0, timestamp=700)  # > 600s later, prunes the first
        self.assertEqual(len(self.window._samples), 1)

    def test_seconds_since_last_sample(self):
        self.window.record(10.0, timestamp=100)
        self.assertAlmostEqual(self.window.seconds_since_last_sample(now=130), 30.0, delta=0.001)


class TestBuildCurrentConditions(unittest.TestCase):
    def setUp(self):
        self.store = SensorStore()
        self.window = WindRollingWindow()

    def test_stale_with_no_samples_returns_error_shape(self):
        result = build_current_conditions(self.store, self.window, stale_after_s=60, device_id="test", now=1000)
        self.assertIsNone(result["data"])
        self.assertIsNotNone(result["error"])

    def test_stale_with_old_sample_returns_error_shape(self):
        self.window.record(10.0, timestamp=0)
        result = build_current_conditions(self.store, self.window, stale_after_s=60, device_id="test", now=1000)
        self.assertIsNone(result["data"])
        self.assertIsNotNone(result["error"])

    def test_fresh_data_returns_full_shape(self):
        now = 1000.0
        self.window.record(16.0934, 270, timestamp=now - 5)  # ~10 mph
        self.store.update(_msg(temperature=68.0, humidity=50.0, rain_total_15min=0.05, rain_rate=0.1,
                                uv_index=3.0, solar_radiation=250.0))

        result = build_current_conditions(self.store, self.window, stale_after_s=60, device_id="test-station", now=now)

        self.assertIsNone(result["error"])
        data = result["data"]
        self.assertEqual(data["did"], "test-station")
        self.assertEqual(data["ts"], int(now))

        iss = data["conditions"][0]
        self.assertEqual(iss["data_structure_type"], 1)
        self.assertAlmostEqual(iss["temp"], 68.0, delta=0.01)
        self.assertAlmostEqual(iss["hum"], 50.0, delta=0.01)
        self.assertAlmostEqual(iss["dew_point"], 48.7, delta=0.2)
        self.assertAlmostEqual(iss["wind_speed_avg_last_2_min"], 10.0, delta=0.05)
        self.assertAlmostEqual(iss["wind_speed_hi_last_10_min"], 10.0, delta=0.05)
        self.assertEqual(iss["wind_dir_at_hi_speed_last_10_min"], 270)
        # 0.05 inches -> 5 hundredths-of-an-inch clicks
        self.assertEqual(iss["rainfall_last_15_min"], 5)
        self.assertAlmostEqual(iss["rain_rate_last"], 0.1, delta=0.001)
        self.assertAlmostEqual(iss["uv_index"], 3.0, delta=0.001)
        self.assertAlmostEqual(iss["solar_rad"], 250.0, delta=0.001)

    def test_barometer_block_omitted_when_absent(self):
        now = 1000.0
        self.window.record(10.0, timestamp=now - 5)
        result = build_current_conditions(self.store, self.window, stale_after_s=60, device_id="test", now=now)
        types = [c["data_structure_type"] for c in result["data"]["conditions"]]
        self.assertNotIn(3, types)

    def test_barometer_block_included_when_fresh(self):
        # SensorStore.update() always stamps with real wall-clock time, so these two
        # barometer tests use real time.time() throughout rather than mixing it with
        # a synthetic epoch (the earlier tests can use a synthetic `now` freely since
        # they never touch the timestamp-gated barometer path).
        now = time.time()
        self.window.record(10.0, timestamp=now - 5)
        self.store.update(_msg(barometric_pressure=1013.25))
        result = build_current_conditions(self.store, self.window, stale_after_s=60, device_id="test", now=now)
        bar = next(c for c in result["data"]["conditions"] if c["data_structure_type"] == 3)
        self.assertAlmostEqual(bar["bar_sea_level"], 29.92, delta=0.02)

    def test_barometer_block_omitted_when_stale(self):
        now = time.time()
        self.window.record(10.0, timestamp=now - 5)
        self.store.update(_msg(barometric_pressure=1013.25))
        # Backdate the stored reading's timestamp directly so the test doesn't need
        # to sleep 60+ real seconds to exercise the staleness path.
        self.store._readings["barometric_pressure"].timestamp_ms -= 120_000
        result = build_current_conditions(self.store, self.window, stale_after_s=60, device_id="test", now=now)
        types = [c["data_structure_type"] for c in result["data"]["conditions"]]
        self.assertNotIn(3, types)

    def test_missing_temp_humidity_defaults_to_zero_not_null(self):
        now = 1000.0
        self.window.record(10.0, timestamp=now - 5)
        result = build_current_conditions(self.store, self.window, stale_after_s=60, device_id="test", now=now)
        iss = result["data"]["conditions"][0]
        self.assertEqual(iss["temp"], 0.0)
        self.assertEqual(iss["hum"], 0.0)
        self.assertEqual(iss["dew_point"], 0.0)


if __name__ == "__main__":
    unittest.main()
