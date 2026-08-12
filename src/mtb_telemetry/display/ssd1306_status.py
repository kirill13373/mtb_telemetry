"""Minimal SH1106 status display for Raspberry Pi logger runtime info."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import time


@dataclass
class OledStatusSnapshot:
    """Three-line snapshot rendered on the 128x64 display."""

    clock_text: str
    status_text: str
    duration_s: float
    samples: int
    queue_blocks: int
    queue_capacity: int
    error_count: int


class OledStatusDisplay:
    """Render compact logger state to SSD1306 over I2C at a controlled refresh rate."""

    def __init__(
        self,
        i2c_port: int = 1,
        i2c_address: int = 0x3C,
        refresh_hz: float = 2.0,
    ) -> None:
        if refresh_hz <= 0:
            raise ValueError("refresh_hz must be > 0")

        try:
            from luma.core.interface.serial import i2c
            from luma.core.render import canvas
            from luma.oled.device import sh1106
        except ImportError as exc:
            raise RuntimeError(
                "OLED dependencies are missing. Install on Pi: "
                "pip install luma.oled pillow smbus2"
            ) from exc

        self._canvas = canvas
        self._serial = i2c(port=i2c_port, address=i2c_address)
        self._device = sh1106(self._serial, width=128, height=64)
        self._device.clear()
        self._refresh_period_s = 1.0 / refresh_hz
        self._next_refresh_s = 0.0
        self._last: OledStatusSnapshot | None = None

    def clear(self) -> None:
        self._device.clear()

    def close(self) -> None:
        self.clear()

    def update(self, snapshot: OledStatusSnapshot, force: bool = False) -> None:
        """Render a snapshot if the refresh interval has elapsed."""
        now = time.monotonic()
        if not force and now < self._next_refresh_s:
            return
        self._next_refresh_s = now + self._refresh_period_s
        self._last = snapshot

        line1 = f"{snapshot.clock_text} {snapshot.status_text}"[:21]
        line2 = f"D:{snapshot.duration_s:6.1f}s S:{snapshot.samples}"[:21]
        line3 = f"Q:{snapshot.queue_blocks}/{snapshot.queue_capacity} E:{snapshot.error_count}"[:21]

        with self._canvas(self._device) as draw:
            draw.text((0, 0), line1, fill="white")
            draw.text((0, 16), line2, fill="white")
            draw.text((0, 32), line3, fill="white")

    @staticmethod
    def clock_now() -> str:
        """Return local wall time in HH:MM:SS format."""
        return datetime.now().strftime("%H:%M:%S")
