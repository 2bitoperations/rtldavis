import argparse
import logging
from . import protocol
from . import dsp

# A dummy packet to satisfy the Message dataclass
dummy_packet = dsp.Packet(index=0, data=b'', rssi=0, snr=0)

def replay_log(log_file: str):
    """
    Replays a sensor log file and prints the decoded values.
    """
    parser = protocol.Parser(symbol_length=14)
    
    with open(log_file, 'r') as f:
        for line in f:
            try:
                parts = line.strip().split(' ')
                if len(parts) != 3:
                    continue
                
                timestamp, iso_time, hex_data = parts
                
                print(f"--- Replaying record from {iso_time} ---")
                
                msg_data = bytes.fromhex(hex_data)
                
                msg_id = msg_data[0] & 0xF
                sensor_id = msg_data[0] >> 4
                
                try:
                    sensor = protocol.Sensor(sensor_id)
                except ValueError:
                    logging.warning(f"Unknown sensor type: 0x{sensor_id:02X}")
                    continue

                # We need to create a dummy dsp.Packet because _parse_sensor_data expects it
                msg = parser._parse_sensor_data(dummy_packet, msg_id, sensor, msg_data)
                
                raw_hex = msg_data.hex()
                log_msg = f"Decoded message for station ID {msg.id} (sensor: {msg.sensor.name}):\n"
                log_msg += f"  Raw data:      {raw_hex}\n"
                log_msg += f"  - Header:      {raw_hex[0:2]} (Sensor ID: {sensor_id}, Station ID: {msg.id})\n"
                log_msg += f"  - Wind Speed:    {raw_hex[2:4]} ({msg.wind_speed} mph)\n"
                log_msg += f"  - Wind Dir:      {raw_hex[4:6]} ({msg.wind_direction} deg)\n"

                sensor_data_hex = raw_hex[6:]
                log_msg += f"  - Sensor data ({msg.sensor.name}): {sensor_data_hex}\n"
                if msg.temperature is not None:
                    log_msg += f"    - Temperature: {msg.temperature}°F\n"
                if msg.humidity is not None:
                    log_msg += f"    - Humidity: {msg.humidity}%\n"
                if msg.rain_rate is not None:
                    log_msg += f"    - Rain Rate: {msg.rain_rate} in/hr\n"
                if msg.rain_total is not None:
                    log_msg += f"    - Rain Total: {msg.rain_total} clicks\n"
                if msg.uv_index is not None:
                    log_msg += f"    - UV Index: {msg.uv_index}\n"
                if msg.solar_radiation is not None:
                    log_msg += f"    - Solar Radiation: {msg.solar_radiation} W/m^2\n"
                if msg.wind_gust_speed is not None:
                    log_msg += f"    - Wind Gust Speed: {msg.wind_gust_speed} mph\n"
                if msg.super_cap_voltage is not None:
                    log_msg += f"    - Super Cap Voltage: {msg.super_cap_voltage} V\n"
                if msg.light is not None:
                    log_msg += f"    - Light: {msg.light}\n"
                
                print(log_msg)

            except Exception as e:
                logging.error(f"Failed to process line: {line.strip()} - {e}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Replay and decode rtldavis sensor logs.")
    parser.add_argument("log_file", help="Path to the sensor.log file.")
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    
    replay_log(args.log_file)
