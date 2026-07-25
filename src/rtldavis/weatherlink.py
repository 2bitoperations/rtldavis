"""
Emulates the local API of a Davis WeatherLink Live hub (GET /v1/current_conditions)
well enough that the rpineau/WeatherLink X2 plugin (TheSkyX, MaximDL) treats this
station as a genuine WeatherLink device for dome/roof-close safety monitoring.
"""
import math
import time
from collections import deque
from typing import Deque, Dict, Optional, Tuple

MPH_PER_KMH = 1.0 / 1.60934
HPA_PER_INHG = 33.8639


class WindRollingWindow:
    """
    Tracks per-packet wind samples so the WeatherLink endpoint can report a true
    rolling average/high independent of HTTP poll timing, and doubles as the
    "last real Davis packet received" heartbeat used for staleness detection.
    """

    _MAX_WINDOW_S = 600.0  # largest window ever queried (10 min)

    def __init__(self) -> None:
        # (timestamp, speed_kmh, direction_deg)
        self._samples: Deque[Tuple[float, float, Optional[int]]] = deque()
        self.last_sample_time: Optional[float] = None

    def record(
        self,
        speed_kmh: float,
        direction_deg: Optional[int] = None,
        timestamp: Optional[float] = None,
    ) -> None:
        now = timestamp if timestamp is not None else time.time()
        self._samples.append((now, speed_kmh, direction_deg))
        self.last_sample_time = now

        cutoff = now - self._MAX_WINDOW_S
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def avg_kmh(self, window_s: float, now: Optional[float] = None) -> float:
        now = now if now is not None else time.time()
        cutoff = now - window_s
        speeds = [s for (t, s, _) in self._samples if t >= cutoff]
        return sum(speeds) / len(speeds) if speeds else 0.0

    def hi_kmh(self, window_s: float, now: Optional[float] = None) -> Tuple[float, Optional[int]]:
        now = now if now is not None else time.time()
        cutoff = now - window_s
        in_window = [(s, d) for (t, s, d) in self._samples if t >= cutoff]
        if not in_window:
            return 0.0, None
        return max(in_window, key=lambda pair: pair[0])

    def seconds_since_last_sample(self, now: Optional[float] = None) -> Optional[float]:
        if self.last_sample_time is None:
            return None
        now = now if now is not None else time.time()
        return now - self.last_sample_time


def dew_point_f(temp_f: float, humidity_pct: float) -> float:
    """Magnus-Tetens dew point. temp_f in degrees F, humidity_pct in 0-100."""
    temp_c = (temp_f - 32.0) * 5.0 / 9.0
    humidity_pct = max(humidity_pct, 0.1)  # avoid log(0) on a bogus 0% reading
    a, b = 17.27, 237.7
    alpha = math.log(humidity_pct / 100.0) + (a * temp_c) / (b + temp_c)
    dew_c = (b * alpha) / (a - alpha)
    return dew_c * 9.0 / 5.0 + 32.0


def build_current_conditions(
    sensor_store,
    wind_window: WindRollingWindow,
    stale_after_s: float,
    device_id: str,
    now: Optional[float] = None,
) -> Dict:
    """
    Builds a WeatherLink-Live-shaped current_conditions response.

    Fails safe: if we haven't received a real Davis packet within `stale_after_s`,
    returns the error shape rather than a fabricated calm/dry reading, since
    downstream astronomy software may use rain/wind fields here to decide
    whether to close an observatory roof.
    """
    now = now if now is not None else time.time()
    age = wind_window.seconds_since_last_sample(now)
    if age is None or age > stale_after_s:
        return {
            "data": None,
            "error": f"No sensor data received in the last {stale_after_s:.0f}s",
        }

    readings = sensor_store.to_response()

    def val(key: str):
        entry = readings.get(key)
        return entry["value"] if entry else None

    temp_f = val("temperature")
    hum = val("humidity")
    dew_f = dew_point_f(temp_f, hum) if temp_f is not None and hum is not None else None

    avg_mph = wind_window.avg_kmh(120.0, now) * MPH_PER_KMH
    hi_kmh, hi_dir = wind_window.hi_kmh(600.0, now)
    hi_mph = hi_kmh * MPH_PER_KMH

    rain_15min_in = val("rain_total_15min") or 0.0
    rain_rate = val("rain_rate") or 0.0

    conditions = [
        {
            "data_structure_type": 1,
            "txid": 1,
            "temp": round(temp_f, 1) if temp_f is not None else 0.0,
            "hum": round(hum, 1) if hum is not None else 0.0,
            "dew_point": round(dew_f, 1) if dew_f is not None else 0.0,
            "wind_speed_avg_last_2_min": round(avg_mph, 1),
            "wind_speed_hi_last_10_min": round(hi_mph, 1),
            "wind_dir_at_hi_speed_last_10_min": hi_dir if hi_dir is not None else 0,
            "rainfall_last_15_min": round(rain_15min_in * 100),
            "rain_rate_last": round(rain_rate, 2),
            "uv_index": round(val("uv_index") or 0.0, 1),
            "solar_rad": round(val("solar_radiation") or 0.0, 1),
        }
    ]

    bar_entry = readings.get("barometric_pressure")
    if bar_entry is not None and (now * 1000 - bar_entry["timestamp_ms"]) / 1000.0 <= stale_after_s:
        conditions.append(
            {
                "data_structure_type": 3,
                "bar_sea_level": round(bar_entry["value"] / HPA_PER_INHG, 3),
            }
        )

    return {
        "data": {
            "did": device_id,
            "ts": int(now),
            "conditions": conditions,
        },
        "error": None,
    }
