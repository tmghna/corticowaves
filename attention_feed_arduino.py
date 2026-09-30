import argparse
import collections
import json
import os
import sys
import threading
import time
import traceback

# SciPy's ducc FFT backend does not accept comma-separated OpenMP thread
# counts such as "8,1"; normalize the inherited environment before importing
# SciPy so Welch PSD cannot abort the acquisition loop.
for _thread_env in ("OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    _thread_value = os.environ.get(_thread_env)
    if _thread_value and "," in _thread_value:
        os.environ[_thread_env] = _thread_value.split(",", 1)[0]

import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi
from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

from corticowaves_dsp import AdaptiveZScoreEngine, calculate_attention_ratio
from hardware.signal_sources import (
    ArduinoFirmataSource,
    Esp32Ads1115SerialSource,
    find_serial_port,
)

FS = 100.0
WINDOW_SEC = 1.5
BUFFER_SIZE = int(FS * WINDOW_SEC)
REFRESH_RATE = 0.1
TELEMETRY_RATE = 20
LOWCUT_HZ = 0.5
HIGHCUT_HZ = 30.0
current_highcut_hz = HIGHCUT_HZ

signal_buffer = collections.deque(maxlen=BUFFER_SIZE)
buffer_lock = threading.Lock()
telemetry_lock = threading.Lock()
telemetry_updated = threading.Event()
latest_raw = None
latest_raw_timestamp = None
latest_dsp_frame = None
latest_source_metadata = {}
sample_received = threading.Event()
display_sum = 0.0
display_count = 0
filter_lock = threading.Lock()
filter_sos = butter(4, (LOWCUT_HZ, HIGHCUT_HZ), btype="bandpass", fs=FS, output="sos")
filter_state = None


def configure_sample_rate(sample_rate_hz, highcut_hz):
    global FS, BUFFER_SIZE, filter_sos, filter_state, current_highcut_hz
    global signal_buffer
    if highcut_hz <= LOWCUT_HZ or sample_rate_hz <= 2 * highcut_hz:
        raise ValueError(
            f"sample rate must be greater than {2 * highcut_hz} Hz "
            f"for the {highcut_hz} Hz cutoff"
        )
    FS = float(sample_rate_hz)
    current_highcut_hz = float(highcut_hz)
    BUFFER_SIZE = max(2, int(round(FS * WINDOW_SEC)))
    with buffer_lock:
        signal_buffer = collections.deque(maxlen=BUFFER_SIZE)
    filter_sos = butter(
        4,
        (LOWCUT_HZ, current_highcut_hz),
        btype="bandpass",
        fs=FS,
        output="sos",
    )
    filter_state = None


def sample_callback(voltage, timestamp, metadata):
    global latest_raw, latest_raw_timestamp, latest_source_metadata
    global filter_state, display_sum, display_count
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
        latest_raw_timestamp = timestamp
        latest_source_metadata = dict(metadata)
    sample_received.set()
    telemetry_updated.set()


def telemetry_publisher(url):
    global display_sum, display_count
    connection_error_reported = False
    while True:
        try:
            with connect(url, open_timeout=2, proxy=None) as websocket:
                print(f"\n[telemetry] connected to {url}", file=sys.stderr)
                connection_error_reported = False
                last_publish_at = 0.0
                while True:
                    telemetry_updated.wait()
                    time_until_publish = (
                        1 / TELEMETRY_RATE - (time.monotonic() - last_publish_at)
                    )
                    if time_until_publish > 0:
                        time.sleep(time_until_publish)
                    with telemetry_lock:
                        sample_count = display_count
                        raw = display_sum / sample_count if sample_count else latest_raw
                        raw_timestamp = latest_raw_timestamp
                        dsp_frame = latest_dsp_frame
                        source_metadata = dict(latest_source_metadata)
                        display_sum = 0.0
                        display_count = 0
                        telemetry_updated.clear()
                    if raw is None or not sample_count:
                        continue
                    packet = {
                        "timestamp": raw_timestamp,
                        "raw": round(raw, 5),
                        "filtered": True,
                        "bandpass": f"{LOWCUT_HZ:g}-{current_highcut_hz:g}Hz",
                        "display_averaged": True,
                        "samples_averaged": sample_count,
                        "sample_rate_hz": FS,
                        **source_metadata,
                    }
                    if dsp_frame is not None:
                        packet.update(dsp_frame)
                    websocket.send(json.dumps(packet))
                    last_publish_at = time.monotonic()
        except (OSError, TimeoutError, WebSocketException) as error:
            if not connection_error_reported:
                print(
                    f"\n[telemetry] cannot reach {url}: {error}; retrying in 2 seconds",
                    file=sys.stderr,
                )
                connection_error_reported = True
            time.sleep(2)


def make_source(args):
    port = args.port or os.environ.get("CORTICOWAVES_DEVICE_PORT") or find_serial_port()
    if not port:
        raise RuntimeError("No hardware serial port found. Pass --port explicitly.")
    if args.backend == "arduino":
        source = ArduinoFirmataSource(
            port=port,
            reference_voltage=args.arduino_reference_voltage,
        )
    else:
        source = Esp32Ads1115SerialSource(
            port=port,
            baudrate=args.baudrate,
            sample_rate_hz=args.sample_rate or 250.0,
        )
    if args.sample_rate is not None and args.backend == "arduino":
        source.sample_rate_hz = args.sample_rate
    return source


def main(args):
    global latest_dsp_frame
    source = make_source(args)
    configure_sample_rate(source.sample_rate_hz, source.highcut_hz)
    try:
        source.start(sample_callback)
        if not sample_received.wait(timeout=5):
            raise RuntimeError(
                f"No samples received from {args.backend} on {source.port} after 5 seconds. "
                "Check the firmware, serial baud rate, ADS1115 wiring, and selected port."
            )
        adaptive_engine = AdaptiveZScoreEngine(
            sampling_rate_hz=1 / REFRESH_RATE,
            window_time_sec=30.0,
            warmup_seconds=5.0,
            sigmoid_gain=1.2,
        )
        threading.Thread(
            target=telemetry_publisher,
            args=(args.telemetry_url,),
            daemon=True,
            name="telemetry-publisher",
        ).start()
        print(f"[*] {args.backend} acquisition started on {source.port}.")
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
        traceback.print_exc()
    finally:
        source.stop()
        print("[*] Acquisition source closed safely.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run live CorticoWaves DSP.")
    parser.add_argument(
        "--backend",
        choices=("arduino", "esp32_ads1115"),
        default=os.environ.get("CORTICOWAVES_BACKEND", "arduino"),
    )
    parser.add_argument("--port", default=None, help="Arduino or ESP32 serial port")
    parser.add_argument(
        "--baudrate",
        type=int,
        default=115200,
        help="ESP32 serial baud rate; firmware defaults to stable 115200 CSV output",
    )
    parser.add_argument(
        "--sample-rate",
        type=float,
        default=None,
        help="Override hardware sample rate; defaults to 100 Hz for Arduino and 250 Hz for ESP32",
    )
    parser.add_argument("--arduino-reference-voltage", type=float, default=5.0)
    parser.add_argument(
        "--telemetry-url",
        default=os.environ.get("CORTICOWAVES_TELEMETRY_URL", "ws://localhost:8765"),
    )
    main(parser.parse_args())
