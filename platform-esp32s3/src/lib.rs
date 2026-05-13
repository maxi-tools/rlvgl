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

/// ESP32-S3 Display driver using SPI DMA targeting an ST7789 panel.
pub struct Esp32s3Display<'d, SPI>
where
    SPI: esp_hal::spi::master::InstanceDma,
{
    interface: SPIInterface<SpiDma<'d, SPI, FullDuplexMode>, Output<'d>>,
    width: u16,
    height: u16,
}

impl<'d, SPI> Esp32s3Display<'d, SPI>
where
    SPI: esp_hal::spi::master::InstanceDma,
{
    /// Wrap a configured SPI DMA channel + D/C pin.
    ///
    /// Call [`Esp32s3Display::init`] after the panel's hardware reset has
    /// settled in order to drive the ST7789 out of sleep and into 16-bit
    /// color mode before issuing any `flush` calls.
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

    /// Run the ST7789 software initialization sequence.
    ///
    /// Sends SWRESET, SLPOUT, COLMOD (RGB565), MADCTL, NORON and DISPON.
    /// The caller is responsible for any inter-command delays required by
    /// the panel datasheet (typically 5 ms after SWRESET and 120 ms after
    /// SLPOUT); supply a delay implementation via `delay_ms`.
    pub fn init<F: FnMut(u32)>(
        &mut self,
        mut delay_ms: F,
    ) -> Result<(), display_interface::DisplayError> {
        // SWRESET
        self.interface.send_commands(DataFormat::U8(&[0x01]))?;
        delay_ms(150);
        // SLPOUT
        self.interface.send_commands(DataFormat::U8(&[0x11]))?;
        delay_ms(120);
        // COLMOD: 16-bit/pixel RGB565
        self.interface.send_commands(DataFormat::U8(&[0x3A]))?;
        self.interface.send_data(DataFormat::U8(&[0x55]))?;
        // MADCTL: top-to-bottom, left-to-right, RGB
        self.interface.send_commands(DataFormat::U8(&[0x36]))?;
        self.interface.send_data(DataFormat::U8(&[0x00]))?;
        // INVON — many ST7789 panels ship with inverted polarity by default.
        self.interface.send_commands(DataFormat::U8(&[0x21]))?;
        // NORON
        self.interface.send_commands(DataFormat::U8(&[0x13]))?;
        delay_ms(10);
        // DISPON
        self.interface.send_commands(DataFormat::U8(&[0x29]))?;
        delay_ms(10);
        Ok(())
    }

    fn set_window(&mut self, area: Rect) -> Result<(), display_interface::DisplayError> {
        // Reject degenerate / out-of-bounds windows so we don't send wrap-around
        // addresses to the panel. width/height are i32 in Rect; cast safely.
        if area.width <= 0
            || area.height <= 0
            || area.x < 0
            || area.y < 0
            || (area.x as u32 + area.width as u32) > self.width as u32
            || (area.y as u32 + area.height as u32) > self.height as u32
        {
            return Err(display_interface::DisplayError::InvalidFormatError);
        }

        let x0 = area.x as u16;
        let y0 = area.y as u16;
        let x1 = x0 + area.width as u16 - 1;
        let y1 = y0 + area.height as u16 - 1;

        // CASET: command 0x2A, then the four address bytes as DATA (D/C high).
        self.interface.send_commands(DataFormat::U8(&[0x2A]))?;
        self.interface.send_data(DataFormat::U8(&[
            (x0 >> 8) as u8,
            x0 as u8,
            (x1 >> 8) as u8,
            x1 as u8,
        ]))?;
        // RASET: command 0x2B, then the four address bytes as DATA.
        self.interface.send_commands(DataFormat::U8(&[0x2B]))?;
        self.interface.send_data(DataFormat::U8(&[
            (y0 >> 8) as u8,
            y0 as u8,
            (y1 >> 8) as u8,
            y1 as u8,
        ]))?;
        // RAMWR opens the pixel data stream; subsequent send_data writes pixels.
        self.interface.send_commands(DataFormat::U8(&[0x2C]))
    }
}

impl<'d, SPI> DisplayDriver for Esp32s3Display<'d, SPI>
where
    SPI: esp_hal::spi::master::InstanceDma,
{
    fn flush(&mut self, area: Rect, colors: &[Color]) {
        if let Err(e) = self.set_window(area) {
            log::error!("Esp32s3Display::set_window failed: {:?}", e);
            return;
        }
        // 320 RGB565 pixels = 640 bytes. Sized to fit comfortably in a single
        // SPI DMA descriptor transfer on the ESP32-S3 while keeping stack use
        // small. Increase only if the configured DMA buffers also grow.
        let mut buf = [0u8; 640];
        let mut i = 0;
        for color in colors {
            let r = (color.0 >> 3) as u16;
            let g = (color.1 >> 2) as u16;
            let b = (color.2 >> 3) as u16;
            let rgb565 = (r << 11) | (g << 5) | b;

            // ST7789 expects big-endian (MSB first) in 16-bit color mode.
            buf[i] = (rgb565 >> 8) as u8;
            buf[i + 1] = rgb565 as u8;
            i += 2;

            if i >= buf.len() {
                if let Err(e) = self.interface.send_data(DataFormat::U8(&buf[..i])) {
                    log::warn!("Esp32s3Display::flush send_data ({} bytes) failed: {:?}", i, e);
                    return;
                }
                i = 0;
            }
        }
        if i > 0 {
            if let Err(e) = self.interface.send_data(DataFormat::U8(&buf[..i])) {
                log::warn!("Esp32s3Display::flush send_data tail ({} bytes) failed: {:?}", i, e);
            }
        }
    }
}

/// ESP32-S3 input device placeholder.
///
/// Touch / button bring-up is intentionally out of scope for this initial
/// platform crate; [`Esp32s3Input::poll`] is an explicit no-op that always
/// returns `None`. Replace with a real driver once the target HW is selected.
pub struct Esp32s3Input;

impl Esp32s3Input {
    /// Create a new instance of the ESP32-S3 input driver stub.
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
        // Intentional no-op; see struct docs.
        None
    }
}
