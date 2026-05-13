# rlvgl-platform-esp32s3

ESP32-S3 hardware support for [rlvgl](../README.md).

Provides:

- `Esp32s3Display` — ST7789 SPI-DMA driver wired to `display-interface-spi`.
  Implements the shared `rlvgl_platform::display::DisplayDriver` trait. The
  driver wraps any `embedded_hal::spi::SpiDevice` (the `aibi_face_demo`
  example wires up an `esp-hal` `SpiDmaBus` via `embedded-hal-bus`'s
  `ExclusiveDevice`) plus a D/C output pin, and exposes an `init()` helper that runs the standard
  ST7789 software bring-up (SWRESET → SLPOUT → COLMOD RGB565 → MADCTL →
  INVON → NORON → DISPON).
- `Esp32s3Input` — explicit no-op input device stub. `poll()` always returns
  `None`; replace once the target HW input path (touch, encoder, buttons)
  is selected.

## Hardware notes

The included [`aibi_face_demo`](examples/aibi_face_demo.rs) example targets a
240×240 ST7789 panel wired to:

| Signal | GPIO  |
| ------ | ----- |
| SCLK   | 12    |
| MOSI   | 11    |
| CS     | 10    |
| D/C    | 9     |
| RST    | 8     |

Backlight control is not wired by this crate; drive the panel's BLK pin from
a host GPIO (or tie it high) in your application. Brightness control via
PWM is out of scope for the initial bring-up — file a follow-up issue if
your board exposes a controllable backlight rail.

## Building the example

```shell
cargo build --release \
    -p rlvgl-platform-esp32s3 \
    --example aibi_face_demo \
    --target xtensa-esp32s3-none-elf \
    -Zbuild-std=core
```

Requires the Xtensa Rust toolchain (`espup install`).
