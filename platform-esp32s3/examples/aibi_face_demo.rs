#![no_std]
#![no_main]

use esp_backtrace as _;
use esp_hal::clock::ClockControl;
use esp_hal::peripherals::Peripherals;
use esp_hal::prelude::*;
use esp_hal::spi::master::Spi;
use esp_hal::spi::SpiMode;
use esp_hal::gpio::Io;
use esp_hal::dma::Dma;
use esp_hal::dma_buffers;
use esp_println::println;

use rlvgl_core::widget::{Color, Rect};
use rlvgl_platform::display::DisplayDriver;
use rlvgl_platform_esp32s3::Esp32s3Display;

#[entry]
fn main() -> ! {
    let peripherals = Peripherals::take();
    let system = peripherals.SYSTEM.split();
    let clocks = ClockControl::boot_defaults(system.clock_control).freeze();

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
        .with_dma(dma_channel.configure(false, &mut descriptors, &mut rx_descriptors, esp_hal::dma::DmaPriority::Priority0));

    let dc_out = esp_hal::gpio::Output::new(dc, esp_hal::gpio::Level::Low);
    let mut rst_out = esp_hal::gpio::Output::new(rst, esp_hal::gpio::Level::High);

    for _ in 0..100000 { unsafe { core::arch::asm!("nop") } }
    rst_out.set_low();
    for _ in 0..100000 { unsafe { core::arch::asm!("nop") } }
    rst_out.set_high();
    for _ in 0..100000 { unsafe { core::arch::asm!("nop") } }

    let mut display = Esp32s3Display::new(spi, dc_out, 240, 240);

    println!("Rendering Aibi Face Demo...");

    let mut colors = [Color(0, 0, 0, 255); 240 * 240];

    for c in colors.iter_mut() {
        *c = Color(0, 0, 128, 255);
    }

    for y in 60..100 {
        for x in 60..100 {
            colors[y * 240 + x] = Color(255, 255, 255, 255);
        }
        for x in 140..180 {
            colors[y * 240 + x] = Color(255, 255, 255, 255);
        }
    }

    display.flush(Rect { x: 0, y: 0, width: 240, height: 240 }, &colors);

    println!("Done.");

    loop {}
}
