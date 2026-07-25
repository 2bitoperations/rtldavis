import asyncio

def setup_integrations(args, sensor_store, mqtt_publisher):
    """
    Sets up the peripheral integrations (REST, WebSockets, Buttons, BME280)
    and returns a list of asyncio task handles that can be cancelled later,
    along with the WebSocket server and the wind rolling-window tracker used
    by the WeatherLink-compatibility endpoint.
    """
    tasks = []
    ws_server = None

    # 1. REST API (GET /sensors and GET /v1/current_conditions)
    from .rest_api import start_rest_server
    from .weatherlink import WindRollingWindow, build_current_conditions

    wind_window = WindRollingWindow()
    device_id = f"rtldavis-station-{args.station_id}" if args.station_id is not None else "rtldavis"

    routes = {
        "/sensors": sensor_store.to_response,
        "/v1/current_conditions": lambda: build_current_conditions(
            sensor_store, wind_window, args.weatherlink_stale_seconds, device_id
        ),
    }
    rest_server_task = asyncio.create_task(start_rest_server(args.http_port, routes))
    tasks.append(rest_server_task)

    # 2. WebSocket Server
    from .websocket_server import start_ws_server
    ws_server = start_ws_server(args.ws_port)

    # 3. Hardware Buttons
    if args.buttons:
        from .buttons import init_buttons
        init_buttons(asyncio.get_running_loop(), ws_server.broadcast)

    # 4. BME280 Sensor
    bme280_task_handle = None
    if args.bme280:
        from .bme280_reader import start_bme280_task
        
        def _handle_bme280(msg):
            sensor_store.update(msg)
            if mqtt_publisher:
                mqtt_publisher.publish(msg)
            if ws_server:
                asyncio.create_task(ws_server.broadcast("sensor", msg.sensor_values))
        
        bme280_task_handle = start_bme280_task(
            bus_num=args.bme280_i2c_bus,
            address=int(args.bme280_i2c_address, 0),
            interval_s=60,
            callback=_handle_bme280
        )
        tasks.append(bme280_task_handle)

    return tasks, ws_server, wind_window
