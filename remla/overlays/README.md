# REMLA Raspberry Pi Overlays

This directory is for Device Tree overlays shipped by `remla`.

## `remla-camera-mux-4port.dtbo`

This is a custom copy of Raspberry Pi's `camera-mux-4port` overlay with one addition: optional boolean I2C parent bus selectors for Raspberry Pi 4 buses `i2c0`, `i2c1`, `i2c3`, `i2c4`, `i2c5`, and `i2c6`.

Example `/boot/firmware/config.txt` lines:

```ini
dtoverlay=i2c-gpio,bus=3,i2c_gpio_sda=23,i2c_gpio_scl=24
dtoverlay=remla-camera-mux-4port,cam0-ov5647,cam1-ov5647,cam2-ov5647,cam3-ov5647,i2c3
```

## `remla-camera-mux-4port-i2c-gpio.dtbo`

This variant supports a single `dtoverlay=i2c-gpio` bus via the `i2c_gpio` selector. It must be loaded after `i2c-gpio`, otherwise firmware cannot resolve the `i2c_gpio` symbol.

Example `/boot/firmware/config.txt` lines:

```ini
dtoverlay=i2c-gpio,i2c_gpio_sda=23,i2c_gpio_scl=24
dtoverlay=remla-camera-mux-4port-i2c-gpio,cam0-ov5647,cam1-ov5647,cam2-ov5647,cam3-ov5647,i2c_gpio
```

The `i2c_gpio` selector assumes only one `dtoverlay=i2c-gpio` bus is defined. Do not set the `bus=` parameter with this variant: Raspberry Pi firmware renames the `i2c-gpio` node when `bus=` is set, but leaves the `i2c_gpio` symbol pointing at the original path, causing later overlays to fail symbol resolution.

The source is in `src/remla-camera-mux-4port-overlay.dts`. It is based on Raspberry Pi's `rpi-6.12.y` `camera-mux-4port-overlay.dts`.

Build from the repo root after cloning Raspberry Pi Linux to `/tmp/raspberrypi-linux`:

```bash
cpp -nostdinc \
  -I /tmp/raspberrypi-linux/include \
  -I /tmp/raspberrypi-linux/arch/arm/boot/dts \
  -I /tmp/raspberrypi-linux/arch/arm/boot/dts/overlays \
  -undef -x assembler-with-cpp \
  remla/overlays/src/remla-camera-mux-4port-overlay.dts \
| dtc -@ -I dts -O dtb \
  -o remla/overlays/remla-camera-mux-4port.dtbo
```

Do not replace Raspberry Pi OS's stock `camera-mux-4port.dtbo`.
