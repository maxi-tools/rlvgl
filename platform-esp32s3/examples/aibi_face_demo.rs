#![no_std]
#![no_main]

use embedded_hal_bus::spi::ExclusiveDevice;
use esp_backtrace as _;
use esp_hal::delay::Delay;
use esp_hal::dma::{Dma, DmaPriority, DmaRxBuf, DmaTxBuf};
use esp_hal::dma_buffers;
use esp_hal::gpio::{Level, Output};
use esp_hal::prelude::*;
use esp_hal::spi::SpiMode;
use esp_hal::spi::master::{Config as SpiConfig, Spi};
use esp_println::println;

use rlvgl_core::widget::{Color, Rect};
use rlvgl_platform::display::DisplayDriver;
use rlvgl_platform_esp32s3::Esp32s3Display;

// 240x240 RGBA8888 ≈ 225 KB — far too large for the default xtensa stack.
// Place the framebuffer in .bss as a static so it lives in DRAM instead.
const W: usize = 240;
const H: usize = 240;
static mut FRAMEBUFFER: [Color; W * H] = [Color(0, 0, 0, 255); W * H];

#[entry]
fn main() -> ! {
    // esp-hal 0.22: a single `init` call replaces the old
    // `Peripherals::take()` + `SYSTEM.split()` + `ClockControl::freeze()`
    // dance. The returned `Peripherals` exposes pins directly as
    // `peripherals.GPIOxx`.
    let peripherals = esp_hal::init(esp_hal::Config::default());

    let sclk = peripherals.GPIO12;
    let mosi = peripherals.GPIO11;
    let cs = peripherals.GPIO10;
    let dc = peripherals.GPIO9;
    let rst = peripherals.GPIO8;

    // ESP32-S3 routes SPI2 to DMA `channel0`; older targets (esp32/esp32s2)
    // would use `dma.spi2channel` instead.
    let dma = Dma::new(peripherals.DMA);
    let dma_channel = dma.channel0;

    // `dma_buffers!` yields four values in 0.22:
    // `(rx_buffer, rx_descriptors, tx_buffer, tx_descriptors)`. The buffers
    // are then wrapped in `DmaRxBuf` / `DmaTxBuf` so `with_buffers` can take
    // ownership of the full DMA state.
    let (rx_buffer, rx_descriptors, tx_buffer, tx_descriptors) = dma_buffers!(32000);
    let dma_rx_buf = DmaRxBuf::new(rx_descriptors, rx_buffer).unwrap();
    let dma_tx_buf = DmaTxBuf::new(tx_descriptors, tx_buffer).unwrap();

    // Build the blocking SPI bus, attach DMA, and bind the framing buffers.
    // CS is *not* wired into the SPI peripheral here — it is driven from
    // the `ExclusiveDevice` wrapper below so that `embedded-hal-bus` can
    // hand back a real `SpiDevice` to `display-interface-spi`.
    let spi = Spi::new_with_config(
        peripherals.SPI2,
        SpiConfig {
            frequency: 40u32.MHz(),
            mode: SpiMode::Mode0,
            ..SpiConfig::default()
        },
    )
    .with_sck(sclk)
    .with_mosi(mosi)
    .with_dma(dma_channel.configure(false, DmaPriority::Priority0))
    .with_buffers(dma_rx_buf, dma_tx_buf);

    let cs_out = Output::new(cs, Level::High);
    let dc_out = Output::new(dc, Level::Low);
    let mut rst_out = Output::new(rst, Level::High);

    let delay = Delay::new();

    // ST7789 hardware reset: hold low for >=10us, release, wait >=120ms.
    delay.delay_millis(10);
    rst_out.set_low();
    delay.delay_millis(10);
    rst_out.set_high();
    delay.delay_millis(120);

    let spi_device =
        ExclusiveDevice::new(spi, cs_out, delay).expect("ExclusiveDevice CS setup failed");

    let mut display = Esp32s3Display::new(spi_device, dc_out, W as u16, H as u16);
    if let Err(e) = display.init(|ms| delay.delay_millis(ms)) {
        println!("Display init failed: {:?}", e);
        loop {}
    }

    println!("Rendering Aibi Face Demo...");

    // SAFETY: single-threaded `#[entry]`; no other references to the static
    // exist. `addr_of_mut!` avoids creating an intermediate reference and
    // satisfies the Rust 2024 `static_mut_refs` lint.
    let colors: &mut [Color; W * H] = unsafe { &mut *core::ptr::addr_of_mut!(FRAMEBUFFER) };

    for c in colors.iter_mut() {
        *c = Color(0, 0, 128, 255);
    }

    for y in 60..100 {
        for x in 60..100 {
            colors[y * W + x] = Color(255, 255, 255, 255);
        }
        for x in 140..180 {
            colors[y * W + x] = Color(255, 255, 255, 255);
        }
    }

    display.flush(
        Rect {
            x: 0,
            y: 0,
            width: W as i32,
            height: H as i32,
        },
        colors,
    );

    println!("Done.");

    loop {}
}
