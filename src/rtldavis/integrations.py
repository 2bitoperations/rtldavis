import asyncio

def setup_integrations(args, sensor_store, mqtt_publisher):
    """
    Sets up the peripheral integrations (REST, WebSockets, Buttons, BME280)
    and returns a list of asyncio task handles that can be cancelled later.
    """
    tasks = []
    ws_server = None

    # 1. REST API
    from .rest_api import start_rest_server
    rest_server_task = asyncio.create_task(
        start_rest_server(args.http_port, sensor_store.to_response)
    )
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

    return tasks, ws_server
