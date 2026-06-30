"""
Minimalny serwis OLED SSD1306 (I2C) dla Raspberry Pi.

Wyświetlanie:
- Linia 1: pełny adres IP
- Linia 2: czas HH:MM + spacja + nazwa stanowiska/hosta
"""

import logging
import threading
from datetime import datetime
from typing import Any, Optional

from app.core import config

logger = logging.getLogger(__name__)


class OledDisplayService:
    """Prosty serwis aktualizujący ekran OLED w osobnym wątku."""

    def __init__(
        self,
        enabled: bool,
        i2c_bus: int,
        i2c_addr: int,
        width: int = 128,
        height: int = 32,
        update_sec: float = 1.0,
    ):
        self.enabled = enabled
        self.i2c_bus = i2c_bus
        self.i2c_addr = i2c_addr
        self.width = width
        self.height = height
        self.update_sec = max(0.2, update_sec)

        self._device: Optional[Any] = None
        self._canvas_ctx: Optional[Any] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False

    def start(self):
        """Uruchamia OLED i pętlę odświeżania."""
        if not self.enabled:
            logger.info("OLED: wyłączony (OLED_ENABLED=False)")
            return

        if self._running:
            return

        try:
            from luma.core.interface.serial import i2c  # type: ignore[import-not-found]
            from luma.core.render import canvas  # type: ignore[import-not-found]
            from luma.oled.device import ssd1306  # type: ignore[import-not-found]

            serial_iface = i2c(port=self.i2c_bus, address=self.i2c_addr)
            self._device = ssd1306(serial_iface, width=self.width, height=self.height)
            self._canvas_ctx = canvas
        except Exception as exc:
            logger.warning("OLED: inicjalizacja nieudana (%s). Backend działa dalej.", exc)
            self._device = None
            self._canvas_ctx = None
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="oled-display", daemon=True)
        self._thread.start()
        self._running = True
        logger.info("OLED: uruchomiony (I2C bus=%s, addr=0x%02X)", self.i2c_bus, self.i2c_addr)

    def stop(self):
        """Zatrzymuje pętlę OLED i czyści ekran."""
        if not self._running:
            return

        self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        try:
            if self._device:
                self._device.clear()
        except Exception:
            pass

        self._thread = None
        self._running = False
        logger.info("OLED: zatrzymany")

    def is_running(self) -> bool:
        return self._running

    def _run_loop(self):
        while not self._stop_event.is_set():
            ip = config.get_local_ip()
            station_id = config.get_station_id()
            hhmm = datetime.now().strftime("%H:%M")
            line2 = f"{hhmm} {station_id}"
            self._render(ip, line2)
            self._stop_event.wait(self.update_sec)

    def _render(self, ip: str, hhmm: str):
        if not self._device or not self._canvas_ctx:
            return

        try:
            with self._canvas_ctx(self._device) as draw:
                draw.text((0, 0), ip, fill="white")
                draw.text((0, 16), hhmm, fill="white")
        except Exception as exc:
            logger.warning("OLED: błąd renderowania (%s)", exc)
