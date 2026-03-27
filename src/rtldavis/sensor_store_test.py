import time
import unittest
from types import SimpleNamespace

from .sensor_store import SensorStore


def _msg(**sensor_values):
    """Build a minimal message stub with the given sensor_values dict."""
    return SimpleNamespace(sensor_values=sensor_values)


class TestSensorStoreMetadata(unittest.TestCase):
    def setUp(self):
        self.store = SensorStore()

    def test_known_sensors_have_metadata(self):
        # Sensors declared by the common decoders should all be pre-loaded.
        for sensor_id in ("wind_speed", "wind_direction", "wind_gust_speed",
                          "temperature", "humidity", "rssi", "snr"):
            self.assertIn(sensor_id, self.store._metadata, f"Missing metadata for {sensor_id}")

    def test_rain_variants_come_from_all_configs(self):
        # RainTotalSensor overrides all_configs to declare these extra keys.
        # SensorStore must pick them up without any rain-specific knowledge of its own.
        for sensor_id in ("rain_total_raw", "rain_total_hourly",
                          "rain_total_daily", "rain_total_weekly"):
            self.assertIn(sensor_id, self.store._metadata, f"Missing metadata for {sensor_id}")

    def test_metadata_units_are_populated(self):
        self.assertEqual(self.store._metadata["wind_speed"].unit_of_measurement, "km/h")
        self.assertEqual(self.store._metadata["temperature"].unit_of_measurement, "°F")
        self.assertEqual(self.store._metadata["humidity"].unit_of_measurement, "%")
        self.assertEqual(self.store._metadata["rain_total_raw"].unit_of_measurement, "in")


class TestSensorStoreUpdate(unittest.TestCase):
    def setUp(self):
        self.store = SensorStore()

    def test_update_stores_value(self):
        self.store.update(_msg(wind_speed=14.5))
        response = self.store.to_response()
        self.assertIn("wind_speed", response)
        self.assertEqual(response["wind_speed"]["value"], 14.5)

    def test_update_ignores_none_values(self):
        self.store.update(_msg(wind_speed=None, temperature=68.0))
        response = self.store.to_response()
        self.assertNotIn("wind_speed", response)
        self.assertIn("temperature", response)

    def test_update_latest_value_wins(self):
        self.store.update(_msg(wind_speed=10.0))
        self.store.update(_msg(wind_speed=20.0))
        self.assertEqual(self.store.to_response()["wind_speed"]["value"], 20.0)

    def test_update_timestamp_is_recent_epoch_millis(self):
        before = int(time.time() * 1000)
        self.store.update(_msg(temperature=70.0))
        after = int(time.time() * 1000)
        ts = self.store.to_response()["temperature"]["timestamp_ms"]
        self.assertGreaterEqual(ts, before)
        self.assertLessEqual(ts, after)

    def test_update_multiple_sensors_in_one_message(self):
        self.store.update(_msg(wind_speed=12.0, temperature=65.0, humidity=55.0))
        response = self.store.to_response()
        self.assertIn("wind_speed", response)
        self.assertIn("temperature", response)
        self.assertIn("humidity", response)

    def test_unknown_sensor_id_still_stored(self):
        # Sensors not in the decoder registry should still be stored;
        # the sensor_id itself is used as the description and units is None.
        self.store.update(_msg(mystery_sensor=42))
        response = self.store.to_response()
        self.assertIn("mystery_sensor", response)
        self.assertEqual(response["mystery_sensor"]["description"], "mystery_sensor")
        self.assertIsNone(response["mystery_sensor"]["units"])


class TestSensorStoreResponseShape(unittest.TestCase):
    def setUp(self):
        self.store = SensorStore()
        self.store.update(_msg(wind_speed=14.5, temperature=70.0))
        self.response = self.store.to_response()

    def test_key_equals_name_field(self):
        for sensor_id, entry in self.response.items():
            self.assertEqual(entry["name"], sensor_id)

    def test_all_required_fields_present(self):
        required = {"name", "description", "value", "timestamp_ms", "units"}
        for sensor_id, entry in self.response.items():
            self.assertEqual(entry.keys(), required, f"Wrong fields for {sensor_id}")

    def test_known_sensor_has_description_and_units(self):
        ws = self.response["wind_speed"]
        self.assertEqual(ws["description"], "Wind Speed")
        self.assertEqual(ws["units"], "km/h")


if __name__ == "__main__":
    unittest.main()
