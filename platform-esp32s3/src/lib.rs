#![no_std]

use rlvgl_core::event::Event;
use rlvgl_core::widget::{Color, Rect};
pub use rlvgl_platform::display::DisplayDriver;
pub use rlvgl_platform::input::InputDevice;

use display_interface::{DataFormat, WriteOnlyDataCommand};
use display_interface_spi::SPIInterface;
use esp_hal::gpio::Output;
use esp_hal::spi::master::SpiDma;
use esp_hal::spi::FullDuplexMode;

/// ESP32-S3 Display driver using SPI DMA.
pub struct Esp32s3Display<'d, SPI>
where
    SPI: esp_hal::spi::master::InstanceDma,
{
    interface: SPIInterface<SpiDma<'d, SPI, FullDuplexMode>, Output<'d>>,
    #[allow(dead_code)]
    width: u16,
    #[allow(dead_code)]
    height: u16,
}

impl<'d, SPI> Esp32s3Display<'d, SPI>
where
    SPI: esp_hal::spi::master::InstanceDma,
{
    /// Create a new instance of the ESP32-S3 display driver.
    pub fn new(
        spi: SpiDma<'d, SPI, FullDuplexMode>,
        dc: Output<'d>,
        width: u16,
        height: u16,
    ) -> Self {
        let interface = SPIInterface::new(spi, dc);
        Self {
            interface,
            width,
            height,
        }
    }

    fn set_window(&mut self, area: Rect) -> Result<(), display_interface::DisplayError> {
        self.interface.send_commands(DataFormat::U8(&[
            0x2A, // CASET
            (area.x >> 8) as u8,
            area.x as u8,
            ((area.x + area.width - 1) >> 8) as u8,
            (area.x + area.width - 1) as u8,
        ]))?;
        self.interface.send_commands(DataFormat::U8(&[
            0x2B, // RASET
            (area.y >> 8) as u8,
            area.y as u8,
            ((area.y + area.height - 1) >> 8) as u8,
            (area.y + area.height - 1) as u8,
        ]))?;
        self.interface.send_commands(DataFormat::U8(&[0x2C])) // RAMWR
    }
}

impl<'d, SPI> DisplayDriver for Esp32s3Display<'d, SPI>
where
    SPI: esp_hal::spi::master::InstanceDma,
{
    fn flush(&mut self, area: Rect, colors: &[Color]) {
        if let Ok(()) = self.set_window(area) {
            let mut buf = [0u8; 640];
            let mut i = 0;
            for color in colors {
                let r = (color.0 >> 3) as u16;
                let g = (color.1 >> 2) as u16;
                let b = (color.2 >> 3) as u16;
                let rgb565 = (r << 11) | (g << 5) | b;

                buf[i] = (rgb565 >> 8) as u8;
                buf[i+1] = rgb565 as u8;
                i += 2;

                if i >= buf.len() {
                    let _ = self.interface.send_data(DataFormat::U8(&buf[..i]));
                    i = 0;
                }
            }
            if i > 0 {
                let _ = self.interface.send_data(DataFormat::U8(&buf[..i]));
            }
        }
    }
}

/// ESP32-S3 Input device (stub).
pub struct Esp32s3Input;

impl Esp32s3Input {
    /// Create a new instance of the ESP32-S3 input driver.
    pub fn new() -> Self {
        Self
    }
}

impl Default for Esp32s3Input {
    fn default() -> Self {
        Self::new()
    }
}

impl InputDevice for Esp32s3Input {
    fn poll(&mut self) -> Option<Event> {
        None
    }
}
