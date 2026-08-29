# camera-mux-4port I2C bus selector modification

This patch preserves the existing Raspberry Pi `camera-mux-4port` positional parameters such as `cam0-ov5647`, `cam1-imx219`, etc., and adds optional boolean bus selector params:

```ini
# create a software I2C bus on GPIO23/GPIO24 as /dev/i2c-3
dtoverlay=i2c-gpio,bus=3,i2c_gpio_sda=23,i2c_gpio_scl=24

# use the normal camera mux overlay params, plus i2c3
dtoverlay=camera-mux-4port,cam0-ov5647,cam1-ov5647,cam2-ov5647,cam3-ov5647,i2c3
```

Supported bus selector params in the patch:

```text
i2c0 i2c1 i2c2 i2c3 i2c4 i2c5 i2c6 i2c7 i2c8 i2c9 i2c10 i2c11
```

Why not `i2cbus=3`?

The overlay fragment needs a Device Tree target phandle like `&i2c3`, while `bus=3` is a runtime/Linux adapter number. Raspberry Pi `__overrides__` can patch properties, but it cannot generally map integer `3` to the symbol `&i2c3`. The robust overlay convention is therefore a boolean selector such as `i2c3`.
