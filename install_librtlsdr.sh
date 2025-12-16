#!/bin/bash

# Script to compile and install the latest librtlsdr (rtl-sdr-blog fork)
# Required for RTL-SDR Blog V4 dongles on older distributions (like Debian Bookworm)

set -e

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root"
  exit 1
fi

echo "Installing build dependencies..."
apt-get update
apt-get install -y git cmake build-essential libusb-1.0-0-dev pkg-config

echo "Cloning rtl-sdr-blog repository..."
cd /tmp
if [ -d "rtl-sdr-blog" ]; then
    rm -rf rtl-sdr-blog
fi
git clone https://github.com/rtlsdrblog/rtl-sdr-blog.git
cd rtl-sdr-blog

echo "Building librtlsdr..."
mkdir build
cd build
cmake ../ -DINSTALL_UDEV_RULES=ON
make

echo "Installing librtlsdr..."
make install

echo "Configuring library path..."
echo "/usr/local/lib" > /etc/ld.so.conf.d/rtlsdr.conf
ldconfig

echo "Blacklisting kernel modules..."
cp ../rtl-sdr.rules /etc/udev/rules.d/
echo 'blacklist dvb_usb_rtl28xxu' > /etc/modprobe.d/blacklist-rtl.conf

echo "Done!"
echo "The old librtlsdr package can sometimes cause conflicts."
echo "It is recommended to remove it with: apt remove librtlsdr0"
echo "Please reboot your system for all changes to take effect."
