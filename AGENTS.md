# Project: rtldavis Python Port

This document outlines the plan and roadmap for porting the `rtldavis` Go application to Python.

## Goal

The primary objective is to re-implement the functionality of the original Go-based `rtldavis` in Python. This includes:

1.  Reading wireless weather data from a Davis Instruments weather station using an RTL-SDR dongle.
2.  Adding support for publishing this data to a Home Assistant instance via MQTT.

## Constraints

-   **Language**: The project will be developed in Python 3.12, unless a critical library necessitates a different version.
-   **Environment Management**: All development and execution will use the `uv` package and environment manager.
-   **Coding Standards**: The codebase will adhere to modern Python best practices, including clear, readable, and maintainable code.

## Project Status

The initial port of the `rtldavis` application from Go to Python is substantially complete. The core functionality, including signal processing, protocol decoding, and data parsing, has been successfully translated.

The current focus is on integrating the application with Home Assistant using the MQTT protocol.

## Home Assistant MQTT Integration Learnings

-   **Discovery Protocol**: Home Assistant's MQTT integration uses a discovery protocol to automatically configure devices. To be discovered, a sensor must have a configuration payload published to a specific topic, typically `homeassistant/sensor/<unique_id>/config`.
-   **Configuration Payload**: This payload is a JSON object that defines the sensor's properties, such as its name, device class, unit of measurement, and state topic.
-   **State Topic**: The `state_topic` specified in the configuration payload tells Home Assistant where to listen for the sensor's state updates. A common pattern is to use a shared state topic for a device (e.g., `rtldavis/<station_id>/state`) and use a `value_template` to extract the relevant value for each sensor.
-   **Device Registry**: To group sensors under a single device in Home Assistant, the configuration payload should include a `device` object with a unique identifier.

## Roadmap

1.  **Initial Setup & Device Enumeration (Done)**
2.  **Port the Digital Signal Processing (DSP) Module (Done)**
3.  **Port the Protocol Decoder (Done)**
4.  **Port the CRC Functions (Done)**
5.  **Integrate Modules and Process Data (Done)**
6.  **Implement MQTT Publisher for Home Assistant (In Progress)**
    -   The application is currently being updated to publish data in a format that Home Assistant can interpret. This involves publishing discovery messages and structuring the data payloads correctly.
7.  **Refinement and Testing**
    -   Implement robust error handling, configuration options (e.g., for MQTT settings), and comprehensive logging.
    -   Conduct end-to-end testing to ensure the system is reliable, from signal reception to data appearing in Home Assistant.
