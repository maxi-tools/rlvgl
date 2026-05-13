#![no_std]
#![no_main]

use esp_backtrace as _;
use esp_hal::clock::ClockControl;
use esp_hal::delay::Delay;
use esp_hal::dma::Dma;
use esp_hal::dma_buffers;
use esp_hal::gpio::Io;
use esp_hal::peripherals::Peripherals;
use esp_hal::prelude::*;
use esp_hal::spi::master::Spi;
use esp_hal::spi::SpiMode;
use esp_println::println;

use rlvgl_core::widget::{Color, Rect};
use rlvgl_platform::display::DisplayDriver;
use rlvgl_platform_esp32s3::Esp32s3Display;

// 240x240 RGB8888 ≈ 225 KB — far too large for the default xtensa stack.
// Place the framebuffer in .bss as a static so it lives in DRAM instead.
const W: usize = 240;
const H: usize = 240;
static mut FRAMEBUFFER: [Color; W * H] = [Color(0, 0, 0, 255); W * H];

#[entry]
fn main() -> ! {
    let peripherals = Peripherals::take();
    let system = peripherals.SYSTEM.split();
    let clocks = ClockControl::boot_defaults(system.clock_control).freeze();
    let delay = Delay::new(&clocks);

    let io = Io::new(peripherals.GPIO, peripherals.IO_MUX);

    let sclk = io.pins.gpio12;
    let mosi = io.pins.gpio11;
    let cs = io.pins.gpio10;
    let dc = io.pins.gpio9;
    let rst = io.pins.gpio8;

    let dma = Dma::new(peripherals.DMA);
    let dma_channel = dma.spi2channel;

    let (mut descriptors, mut rx_descriptors) = dma_buffers!(32000);

    let spi = Spi::new(peripherals.SPI2, 40.MHz(), SpiMode::Mode0, &clocks)
        .with_pins(Some(sclk), Some(mosi), None, Some(cs))
        .with_dma(dma_channel.configure(
            false,
            &mut descriptors,
            &mut rx_descriptors,
            esp_hal::dma::DmaPriority::Priority0,
        ));

    let dc_out = esp_hal::gpio::Output::new(dc, esp_hal::gpio::Level::Low);
    let mut rst_out = esp_hal::gpio::Output::new(rst, esp_hal::gpio::Level::High);

    // ST7789 hardware reset: hold low for >=10us, release, wait >=120ms.
    delay.delay_millis(10);
    rst_out.set_low();
    delay.delay_millis(10);
    rst_out.set_high();
    delay.delay_millis(120);

    let mut display = Esp32s3Display::new(spi, dc_out, W as u16, H as u16);
    if let Err(e) = display.init(|ms| delay.delay_millis(ms)) {
        println!("Display init failed: {:?}", e);
        loop {}
    }

    println!("Rendering Aibi Face Demo...");

    // SAFETY: single-threaded `#[entry]`; no other references exist.
    let colors = unsafe { &mut FRAMEBUFFER };

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
