"""Hardware sample sources for the shared CorticoWaves DSP pipeline."""

from __future__ import annotations

import json
import sys
import threading
import time
from collections.abc import Callable

import serial
import serial.tools.list_ports
from pyfirmata2 import Arduino

SampleCallback = Callable[[float, float, dict[str, object]], None]


def find_serial_port() -> str | None:
    """Find a likely Arduino or ESP32 serial port."""
    ports = list(serial.tools.list_ports.comports())
    for port in ports:
        description = port.description or ""
        device = port.device or ""
        if (
            any(token in description.lower() for token in ("arduino", "esp32", "usb serial"))
            or any(token in device.lower() for token in ("ttyacm", "ttyusb", "usbmodem", "usbserial"))
        ):
            return device
    for port in ports:
        if (port.device or "").upper().startswith("COM"):
            return port.device
    return None


class ArduinoFirmataSource:
    """Read normalized A0 samples from an Arduino StandardFirmata board."""

    sample_rate_hz = 100.0
    highcut_hz = 30.0

    def __init__(self, port: str, reference_voltage: float = 5.0) -> None:
        self.port = port
        self.reference_voltage = reference_voltage
        self.board = None

    def start(self, callback: SampleCallback) -> None:
        self.board = Arduino(self.port)
        self.board.samplingOn(round(1000 / self.sample_rate_hz))
        pin = self.board.get_pin("a:0:i")

        def on_sample(data):
            if data is not None:
                callback(
                    float(data) * self.reference_voltage,
                    time.time(),
                    {
                        "source": "arduino",
                        "adc_backend": "firmata",
                        "adc_resolution_bits": 10,
                        "channel": "A0",
                    },
                )

        pin.register_callback(on_sample)
        pin.enable_reporting()

    def stop(self) -> None:
        if self.board is not None:
            self.board.exit()
            self.board = None


class Esp32Ads1115SerialSource:
    """Read compact CSV or legacy JSON samples from ESP32 ADS1115 firmware."""

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        sample_rate_hz: float = 250.0,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.sample_rate_hz = sample_rate_hz
        self.highcut_hz = 50.0
        self.serial = None
        self.stop_event = threading.Event()
        self.reader_thread = None

    def start(self, callback: SampleCallback) -> None:
        self.serial = serial.Serial(self.port, self.baudrate, timeout=1)
        self.stop_event.clear()
        self.reader_thread = threading.Thread(
            target=self._read_loop,
            args=(callback,),
            daemon=True,
            name="esp32-ads1115-serial",
        )
        self.reader_thread.start()

    def _read_loop(self, callback: SampleCallback) -> None:
        assert self.serial is not None
        invalid_lines = 0
        while not self.stop_event.is_set():
            line = self.serial.readline()
            if not line:
                continue
            try:
                text = line.decode("utf-8").strip()
                if text.startswith("{"):
                    packet = json.loads(text)
                    if "error" in packet:
                        print(f"[esp32] firmware error: {packet['error']}", file=sys.stderr)
                        continue
                    voltage = float(packet["voltage"])
                    device_timestamp = packet.get("timestamp")
                    sequence = packet.get("sequence")
                    channel = packet.get("channel", "A0")
                    gain = packet.get("gain", "2/3")
                else:
                    fields = text.split(",")
                    if fields[:1] == ["ERROR"]:
                        print(f"[esp32] firmware error: {','.join(fields[1:])}", file=sys.stderr)
                        continue
                    if fields[:1] in (["BOOT"], ["READY"], ["ADS1115"]):
                        print(f"[esp32] firmware: {text}", file=sys.stderr)
                        continue
                    if len(fields) != 5 or fields[0] != "S":
                        raise ValueError("unsupported serial packet")
                    sequence = int(fields[1])
                    device_timestamp = int(fields[2]) / 1_000_000
                    voltage = float(fields[4])
                    channel = "A0"
                    gain = "2/3"
                timestamp = time.time()
                metadata = {
                    "source": "esp32_ads1115",
                    "adc_backend": "ads1115",
                    "adc_resolution_bits": 16,
                    "channel": channel,
                    "ads1115_gain": gain,
                    "sample_sequence": sequence,
                    "device_timestamp": device_timestamp,
                }
            except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                invalid_lines += 1
                if invalid_lines <= 3:
                    print(
                        f"[esp32] ignored serial line ({error}): {line[:120]!r}",
                        file=sys.stderr,
                    )
                continue
            callback(voltage, timestamp, metadata)

    def stop(self) -> None:
        self.stop_event.set()
        if self.reader_thread is not None:
            self.reader_thread.join(timeout=2)
            self.reader_thread = None
        if self.serial is not None:
            self.serial.close()
            self.serial = None
