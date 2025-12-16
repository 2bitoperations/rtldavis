#!/bin/bash

# rtldavis Installer/Updater for Raspberry Pi OS (Bookworm/Trixie)

set -e

SERVICE_NAME="rtldavis"
INSTALL_DIR="/opt/rtldavis"
CONFIG_FILE="/etc/default/rtldavis"
SERVICE_FILE="/etc/systemd/system/rtldavis.service"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root"
  exit 1
fi

# Check for uv, install if missing
if ! command -v uv &> /dev/null; then
    echo "uv not found. Installing uv for root..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Add uv to path for this session
    export PATH="/root/.local/bin:$PATH"
fi

UV_BIN=$(command -v uv)
if [ -z "$UV_BIN" ]; then
    # Fallback if command -v still fails but we know where it should be
    if [ -f "/root/.local/bin/uv" ]; then
        UV_BIN="/root/.local/bin/uv"
    else
        echo "Failed to install/find uv. Please install it manually."
        exit 1
    fi
fi

echo "Using uv at: $UV_BIN"

# Check for update flag
UPDATE_MODE=false
if [ "$1" == "--update" ]; then
    UPDATE_MODE=true
fi

if [ "$UPDATE_MODE" = true ]; then
    echo "Updating rtldavis from git..."
    # Check if we are in a git repository
    if [ -d ".git" ]; then
        echo "Pulling latest changes from origin/master..."
        # Run git pull as the original user to avoid permission issues if the repo is owned by them
        if [ -n "$SUDO_USER" ]; then
             sudo -u "$SUDO_USER" git pull origin master
        else
             git pull origin master
        fi
    else
        echo "Error: Not a git repository. Cannot pull updates."
        exit 1
    fi
fi

echo "Installing/Updating rtldavis..."

# Stop service if running
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "Stopping existing service..."
    systemctl stop "$SERVICE_NAME"
fi

# Create installation directory if it doesn't exist
if [ ! -d "$INSTALL_DIR" ]; then
    echo "Creating installation directory: $INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"
fi

# Copy project files (excluding .venv and .git if copying from a local dev env)
echo "Copying project files..."
rsync -av --exclude='.venv' --exclude='.git' --exclude='__pycache__' . "$INSTALL_DIR"

# Set permissions
chown -R root:root "$INSTALL_DIR"

# Create/Update virtual environment and install dependencies
echo "Setting up virtual environment and installing dependencies..."
cd "$INSTALL_DIR"
"$UV_BIN" sync --all-extras

# Create configuration file if it doesn't exist
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Creating configuration file: $CONFIG_FILE"
    cat <<EOF > "$CONFIG_FILE"
# rtldavis Configuration

# RTL-SDR Device (serial or index, default: 0)
RTLDAVIS_DEVICE="0"

# Frequency Correction in PPM (default: 0)
RTLDAVIS_PPM=0

# Tuner Gain (default: auto)
RTLDAVIS_GAIN="auto"

# Disable frequency hopping (default: false)
# RTLDAVIS_NO_HOP=true

# MQTT Broker Settings
RTLDAVIS_MQTT_BROKER="localhost"
RTLDAVIS_MQTT_PORT=1883
RTLDAVIS_MQTT_USERNAME=""
RTLDAVIS_MQTT_PASSWORD=""
RTLDAVIS_MQTT_CLIENT_ID="davis-weather"
RTLDAVIS_MQTT_DISCOVERY_PREFIX="homeassistant"
RTLDAVIS_MQTT_STATE_PREFIX="rtldavis"

# Station ID (optional, 0-7)
# RTLDAVIS_STATION_ID=0
EOF
else
    echo "Configuration file already exists: $CONFIG_FILE (skipping overwrite)"
fi

# Create systemd service file (always overwrite to ensure latest config)
echo "Creating/Updating systemd service file: $SERVICE_FILE"
cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=rtldavis Weather Station Receiver
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$CONFIG_FILE
# Force usage of /usr/local/lib for newer librtlsdr
Environment="LD_LIBRARY_PATH=/usr/local/lib"
ExecStart=$INSTALL_DIR/.venv/bin/python -m rtldavis \\
    --rtlsdr-device \${RTLDAVIS_DEVICE} \\
    --ppm \${RTLDAVIS_PPM} \\
    --gain \${RTLDAVIS_GAIN} \\
    \${RTLDAVIS_NO_HOP:+--no-hop} \\
    --mqtt-broker \${RTLDAVIS_MQTT_BROKER} \\
    --mqtt-port \${RTLDAVIS_MQTT_PORT} \\
    --mqtt-username \${RTLDAVIS_MQTT_USERNAME} \\
    --mqtt-password \${RTLDAVIS_MQTT_PASSWORD} \\
    --mqtt-client-id \${RTLDAVIS_MQTT_CLIENT_ID} \\
    --mqtt-discovery-prefix \${RTLDAVIS_MQTT_DISCOVERY_PREFIX} \\
    --mqtt-state-prefix \${RTLDAVIS_MQTT_STATE_PREFIX} \\
    \${RTLDAVIS_STATION_ID:+--station-id \${RTLDAVIS_STATION_ID}}

Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd and enable service
echo "Reloading systemd and enabling service..."
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

# Start service
echo "Starting service..."
systemctl start "$SERVICE_NAME"

echo "Installation/Update complete!"
echo "Service status:"
systemctl status "$SERVICE_NAME" --no-pager
