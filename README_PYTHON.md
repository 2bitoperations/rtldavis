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

## Setup and Testing

To set up the development environment and run the tests, you will need to have `uv` installed.

1.  **Install Dependencies (including test dependencies)**:
    ```bash
    uv sync --all-extras
    ```

2.  **Run Tests**:
    ```bash
    uv run pytest
    ```

## Roadmap for Porting from Go

The porting process will be staged to ensure a structured and manageable transition. The following roadmap is based on the structure of the original Go application:

1.  **Initial Setup & Device Enumeration (Done)**
    -   Set up the Python project with `pyproject.toml`.
    -   Add initial dependencies, including `pyrtlsdr`.
    -   Implement basic RTL-SDR device enumeration to confirm hardware detection.

2.  **Port the Digital Signal Processing (DSP) Module (`dsp/`)**
    -   Translate the Go DSP functions to Python, likely using libraries like `NumPy` and `SciPy`.
    -   Key tasks will include implementing the FSK demodulator, filtering, and signal normalization logic.

3.  **Port the Protocol Decoder (`protocol/`)**
    -   Implement the logic to decode the Davis Instruments wireless protocol.
    -   This will involve understanding the packet structure, data encoding, and different sensor types.

4.  **Port the CRC Functions (`crc/`)**
    -   Translate the CRC (Cyclic Redundancy Check) calculation and validation logic to Python.
    -   This is a critical step for ensuring the integrity of the received data packets.

5.  **Integrate Modules and Process Data**
    -   Combine the DSP, protocol, and CRC modules in the main application loop.
    -   The application will read data from the RTL-SDR, process it through the DSP pipeline, decode the packets, and validate their CRCs.

6.  **Implement MQTT Publisher for Home Assistant**
    -   Integrate an MQTT client library (e.g., `paho-mqtt`).
    -   Format the decoded weather data into a structure suitable for Home Assistant (e.g., JSON).
    -   Publish the data to an MQTT broker, allowing for integration with Home Assistant.

7.  **Refinement and Testing**
    -   Implement robust error handling, configuration options (e.g., for MQTT settings), and comprehensive logging.
    -   Conduct end-to-end testing to ensure the system is reliable, from signal reception to data appearing in Home Assistant.
