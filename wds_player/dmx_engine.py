"""DMX512 изход през хардуерния UART на Raspberry Pi към TTL-RS485 модул.

Всеки DMX пакет:  BREAK (>=88 µs, линия = 0) -> MAB (>=8 µs, линия = 1)
                  -> Start Code 0x00 -> 512 байта данни, 250 000 bps, 8N2.

Режими за генериране на BREAK (`break_mode`):
    "break" - TIOCSBRK/TIOCCBRK (pyserial break_condition) + активно изчакване
              с time.perf_counter(). Отговаря на примера от заданието.
    "baud"  - временно сваляне на скоростта до 96 000 bps и изпращане на 0x00:
              старт бит + 8 нулеви бита = 93.75 µs BREAK, стоп битовете = MAB.
              По-стабилно време, ако "break" дава jitter.

ВАЖНО: на Pi 3 /dev/serial0 трябва да сочи към PL011 (ttyAMA0). Mini UART-ът
(ttyS0) не поддържа 2 стоп бита - вж. README.md (dtoverlay=disable-bt).
"""

from __future__ import annotations

import threading
import time

try:
    import serial
except ImportError:  # позволява симулация без pyserial
    serial = None

DEFAULT_PORT = "/dev/serial0"
DMX_BAUD = 250_000
BREAK_BAUD = 96_000
DMX_CHANNELS = 512
START_CODE = b"\x00"
BLACKOUT = bytes(DMX_CHANNELS)
BYTE_TIME = 11 / DMX_BAUD       # 1 старт + 8 данни + 2 стоп бита
TX_GUARD = 0.0007               # запас за последните байтове във FIFO на UART-а


class DMXError(Exception):
    pass


def _spin(seconds: float) -> None:
    """Активно изчакване - по-точно от time.sleep() за десетки µs."""
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        pass


MIN_CHANNELS = 24          # стандартът изисква поне 24 слота в пакет


def clamp_channels(n) -> int:
    try:
        return min(DMX_CHANNELS, max(MIN_CHANNELS, int(n)))
    except (TypeError, ValueError):
        return DMX_CHANNELS


def _normalize(channels, count: int = DMX_CHANNELS) -> bytes:
    data = bytes(channels[:count])
    if len(data) < count:
        data += bytes(count - len(data))
    return data


class DMXOutput:
    """Реален DMX изход през pyserial."""

    def __init__(self, port: str = DEFAULT_PORT, break_mode: str = "break",
                 break_us: int = 110, mab_us: int = 16, de_gpio: int | None = None):
        if break_mode not in ("break", "baud"):
            raise ValueError("break_mode трябва да е 'break' или 'baud'")
        self.port = port
        self.break_mode = break_mode
        self.break_s = break_us / 1e6
        self.mab_s = mab_us / 1e6
        self.de_gpio = de_gpio
        self.channels = DMX_CHANNELS    # брой слотове в пакета (по-малко = по-бърз пакет)
        self._ser = None
        self._de = None
        self._tx_end = 0.0      # кога предишният пакет е излязъл от UART-а (perf_counter)
        self._lock = threading.Lock()

    def set_channels(self, n) -> None:
        self.channels = clamp_channels(n)

    @property
    def description(self) -> str:
        return f"{self.port} ({self.break_mode})"

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def open(self) -> None:
        if serial is None:
            raise DMXError("pyserial не е инсталиран: sudo apt install python3-serial")
        if self.de_gpio is not None:
            # Модул с MAX485 без авто-посока: DE/RE = 1 -> режим предаване.
            try:
                from gpiozero import OutputDevice
                self._de = OutputDevice(self.de_gpio, initial_value=True)
            except Exception as e:
                raise DMXError(f"GPIO {self.de_gpio} (DE/RE) не може да се управлява: {e}") from e
        try:
            self._ser = serial.Serial(
                self.port,
                baudrate=DMX_BAUD,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_TWO,
                timeout=0,
                write_timeout=1,
            )
        except (serial.SerialException, OSError) as e:
            raise DMXError(f"Портът {self.port} не може да се отвори: {e}") from e

    def _send_break(self) -> None:
        ser = self._ser
        if self.break_mode == "break":
            ser.break_condition = True
            _spin(self.break_s)
            ser.break_condition = False
            _spin(self.mab_s)
        else:
            ser.baudrate = BREAK_BAUD
            ser.write(b"\x00")
            ser.flush()
            ser.baudrate = DMX_BAUD

    def _wait_tx(self) -> None:
        """Изчаква предишният пакет да излезе от UART-а, преди следващият BREAK.

        Не се ползва flush() (tcdrain) след записа: ядрото го изчаква със заспиване,
        закръглено до jiffy (10-20 ms), и затваря кадъра на ~40 ms - колкото целия
        период при 25 fps, така че от време на време кадър се пропуска. Вместо това
        записът се връща веднага, а времето за предаване (22.6 ms) се изчаква тук - и
        то само ако още не е изтекло от паузата между кадрите."""
        remaining = self._tx_end - time.perf_counter()
        if remaining > 0.002:
            time.sleep(remaining - 0.002)
        while time.perf_counter() < self._tx_end:
            pass
        if self._ser.out_waiting:       # (рядко) още има байтове в буфера на ядрото
            self._ser.flush()

    def send(self, channels) -> None:
        """Изпраща един пълен DMX пакет. Връща се веднага след записа; следващото
        извикване изчаква края на предаването (вж. _wait_tx)."""
        if not self.is_open:
            raise DMXError("DMX портът не е отворен")
        packet = START_CODE + _normalize(channels, self.channels)
        with self._lock:
            try:
                self._wait_tx()
                self._send_break()
                self._ser.write(packet)
                self._tx_end = time.perf_counter() + len(packet) * BYTE_TIME + TX_GUARD
            except (serial.SerialException, OSError) as e:
                raise DMXError(f"Грешка при запис в {self.port}: {e}") from e

    def blackout(self) -> None:
        self.send(BLACKOUT)

    def close(self) -> None:
        with self._lock:
            if self._ser is not None:
                try:
                    self._wait_tx()      # последният пакет (напр. Blackout) да излезе докрай
                except (serial.SerialException, OSError):
                    pass
                try:
                    self._ser.close()
                finally:
                    self._ser = None
            if self._de is not None:
                self._de.close()
                self._de = None


class NullDMXOutput:
    """Симулиран изход (за разработка на PC без RS485 хардуер)."""

    # 513 байта * 11 бита / 250 kbps ≈ 22.6 ms + break
    FRAME_TIME = (1 + DMX_CHANNELS) * 11 / DMX_BAUD + 0.000130

    def __init__(self, simulate_timing: bool = True):
        self.channels = DMX_CHANNELS
        self.simulate_timing = simulate_timing
        self.last_frame = BLACKOUT
        self.frames_sent = 0
        self._open = False

    description = "симулация (без хардуер)"

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        self._open = True

    def set_channels(self, n) -> None:
        self.channels = clamp_channels(n)

    def send(self, channels) -> None:
        self.last_frame = _normalize(channels)
        self.frames_sent += 1
        if self.simulate_timing:
            time.sleep((1 + self.channels) * 11 / DMX_BAUD + 0.000130)

    def blackout(self) -> None:
        self.send(BLACKOUT)

    def close(self) -> None:
        self._open = False
