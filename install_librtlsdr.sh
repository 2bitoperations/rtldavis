#!/bin/bash

# Script to compile and install the latest librtlsdr (steve-m fork)
# Required for RTL-SDR Blog V4 dongles on older distributions (like Debian Bookworm)

set -e

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root"
  exit 1
fi

echo "Installing build dependencies..."
apt-get update
apt-get install -y libusb-1.0-0-dev git cmake debhelper

echo "Cloning librtlsdr repository..."
cd /tmp
if [ -d "librtlsdr" ]; then
    echo "Removing existing librtlsdr directory..."
    rm -rf librtlsdr
fi
git clone https://github.com/steve-m/librtlsdr.git
cd librtlsdr

echo "Building Debian packages..."
dpkg-buildpackage -b --no-sign

echo "Installing Debian packages..."
cd ..
dpkg -i librtlsdr0_*.deb
dpkg -i librtlsdr-dev_*.deb
dpkg -i rtl-sdr_*.deb

echo "Blacklisting kernel modules..."
# The package installation might handle this, but let's be safe
echo 'blacklist dvb_usb_rtl28xxu' > /etc/modprobe.d/blacklist-rtl.conf

echo "Done! Please reboot your system for all changes to take effect."
