import argparse
import collections
import json
import os
import sys
import threading
import time

import numpy as np
import serial.tools.list_ports
from pyfirmata2 import Arduino
from scipy.signal import butter, sosfilt, sosfilt_zi
from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

from corticowaves_dsp import AdaptiveZScoreEngine, calculate_attention_ratio

FS = 100
WINDOW_SEC = 1.5
BUFFER_SIZE = int(FS * WINDOW_SEC)
REFRESH_RATE = 0.1
TELEMETRY_RATE = 20
LOWCUT_HZ = 0.5
HIGHCUT_HZ = 30.0

signal_buffer = collections.deque(maxlen=BUFFER_SIZE)
buffer_lock = threading.Lock()
telemetry_lock = threading.Lock()
telemetry_updated = threading.Event()
latest_raw = None
latest_raw_timestamp = None
latest_dsp_frame = None
display_sum = 0.0
display_count = 0
filter_lock = threading.Lock()
filter_sos = butter(4, (LOWCUT_HZ, HIGHCUT_HZ), btype="bandpass", fs=FS, output="sos")
filter_state = None


def find_arduino_port():
    ports = list(serial.tools.list_ports.comports())
    for port in ports:
        description = port.description or ""
        device = port.device or ""
        if (
            "Arduino" in description
            or "ttyACM" in device
            or "ttyUSB" in device
            or "usbmodem" in device
            or "usbserial" in device
        ):
            return device
    for port in ports:
        if (port.device or "").upper().startswith("COM"):
            return port.device
    return None


def bioamp_callback(data):
    global latest_raw, latest_raw_timestamp, filter_state, display_sum, display_count
    if data is None:
        return
    voltage = data * 5.0
    with filter_lock:
        if filter_state is None:
            filter_state = sosfilt_zi(filter_sos) * voltage
        filtered, filter_state = sosfilt(filter_sos, [voltage], zi=filter_state)
    eeg_signal = float(filtered[0])
    with buffer_lock:
        signal_buffer.append(eeg_signal)
    with telemetry_lock:
        display_sum += eeg_signal
        display_count += 1
        latest_raw = round(eeg_signal, 5)
        latest_raw_timestamp = time.time()
    telemetry_updated.set()


def telemetry_publisher(url):
    global display_sum, display_count
    while True:
        try:
            with connect(url, open_timeout=2) as websocket:
                while True:
                    telemetry_updated.wait(timeout=1 / TELEMETRY_RATE)
                    with telemetry_lock:
                        sample_count = display_count
                        raw = display_sum / sample_count if sample_count else latest_raw
                        raw_timestamp = latest_raw_timestamp
                        dsp_frame = latest_dsp_frame
                        display_sum = 0.0
                        display_count = 0
                        telemetry_updated.clear()
                    if raw is None or not sample_count:
                        continue
                    packet = {
                        "timestamp": raw_timestamp,
                        "raw": round(raw, 5),
                        "filtered": True,
                        "bandpass": "0.5-30Hz",
                        "display_averaged": True,
                        "samples_averaged": sample_count,
                        "source": "arduino",
                    }
                    if dsp_frame is not None:
                        packet.update(dsp_frame)
                    websocket.send(json.dumps(packet))
        except (OSError, TimeoutError, WebSocketException):
            time.sleep(2)


def main(telemetry_url="ws://localhost:8765", port_override=None):
    global latest_dsp_frame
    port = port_override or os.environ.get("CORTICOWAVES_ARDUINO_PORT") or find_arduino_port()
    if not port:
        print("Error: Could not auto-detect Arduino port. Check USB connection.")
        sys.exit(1)
    print(f"[*] Arduino port: {port}")
    adaptive_engine = AdaptiveZScoreEngine(
        sampling_rate_hz=1 / REFRESH_RATE,
        window_time_sec=30.0,
        warmup_seconds=5.0,
        sigmoid_gain=1.2,
    )
    try:
        board = Arduino(port)
        print("[*] Firmata connection established.")
        board.samplingOn(10)
        bioamp_pin = board.get_pin("a:0:i")
        bioamp_pin.register_callback(bioamp_callback)
        bioamp_pin.enable_reporting()
        threading.Thread(
            target=telemetry_publisher,
            args=(telemetry_url,),
            daemon=True,
            name="telemetry-publisher",
        ).start()
        print("[*] Live adaptive Z-score warm-up active; no pre-session calibration required.")
        while True:
            with buffer_lock:
                signal_snapshot = (
                    np.array(signal_buffer) if len(signal_buffer) == BUFFER_SIZE else None
                )
            if signal_snapshot is not None:
                p_alpha, p_beta, ratio = calculate_attention_ratio(
                    signal_snapshot, FS, BUFFER_SIZE
                )
                frame = adaptive_engine.update(ratio)
                frame.update({
                    "alpha_power": p_alpha,
                    "beta_power": p_beta,
                    "attention_ratio": ratio,
                    "warmup": not adaptive_engine.is_warmed_up,
                })
                with telemetry_lock:
                    latest_dsp_frame = frame
                telemetry_updated.set()
                sys.stdout.write(
                    f"\rAlpha {p_alpha:.6f} | Beta {p_beta:.6f} | "
                    f"Ratio {ratio:.4f} | Z {frame['z_score']:.3f} | "
                    f"Drive {frame['attention_metric']:.3f}"
                )
                sys.stdout.flush()
            time.sleep(REFRESH_RATE)
    except KeyboardInterrupt:
        print("\n[*] CorticoWaves DSP pipeline stopped.")
    except Exception as error:
        print(f"\n[!] Unexpected error: {error}")
    finally:
        if "board" in locals():
            board.exit()
            print("[*] Serial interface closed safely.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run live CorticoWaves Arduino DSP.")
    parser.add_argument("--port", default=None, help="Arduino serial port override")
    parser.add_argument(
        "--telemetry-url",
        default=os.environ.get("CORTICOWAVES_TELEMETRY_URL", "ws://localhost:8765"),
    )
    args = parser.parse_args()
    main(args.telemetry_url, args.port)
