# CorticoWaves

CorticoWaves is a corticothalamic neural-field project. The current pipeline
uses an Arduino analog input and BioAmp EXG Pill without an ADS1115 converter:

```text
Arduino @ 100 Hz
  -> 0.5-30 Hz streaming band-pass
  -> 1.5 s Welch power window
  -> Welch PSD
  -> raw Beta / Alpha attention ratio
  -> 0.4 s ratio pre-smoothing
  -> 5 s warm-up
  -> adaptive 30 s EWMA Z-score
  -> sigmoid drive parameter in [0, 1]
  -> local WebSocket bridge
  -> Astro dashboard and attention-controlled rocket game
```

## Requirements

- Python 3.10 or newer
- Node.js 20 or newer and npm
- Arduino IDE
- Arduino running the `StandardFirmata` example
- BioAmp EXG Pill and electrodes
- USB data cable

The Python dependencies are in `requirements.txt`:

- NumPy and SciPy for filtering and PSD
- pySerial and pyFirmata2 for Arduino/Firmata
- websockets for the local telemetry bridge
- Pygame for the standalone desktop rocket prototype

## First-time setup: Linux and macOS

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Install Node.js 20+ using your preferred package manager, then install the
dashboard dependencies:

```bash
cd dashboard
npm install
cd ..
```

On Linux, the user running the program may need serial-port permission:

```bash
sudo usermod -aG dialout "$USER"
```

Log out and back in after changing the group. Some distributions use a
different group; inspect the port permissions with `ls -l /dev/ttyACM0`.

On macOS, Arduino ports usually look like `/dev/cu.usbmodem*` or
`/dev/cu.usbserial*`. No `dialout` step is required.

## First-time setup: Windows PowerShell

Install Python 3.10+ and Node.js 20+ from their official installers. In
PowerShell, from the repository root:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cd dashboard
npm install
cd ..
```

If PowerShell blocks activation for the current user, run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then activate the environment again. Windows Arduino ports normally appear as
`COM3`, `COM4`, and so on. Find the number in Arduino IDE under
**Tools > Port**, or with:

```powershell
python -m serial.tools.list_ports -v
```

## Arduino firmware setup

1. Open Arduino IDE.
2. Select **File > Examples > Firmata > StandardFirmata**.
3. Select the correct board under **Tools > Board**.
4. Select the USB port under **Tools > Port**.
5. Upload the sketch.
6. Close Serial Monitor before running Python; it can lock the port.

The software auto-detects common Arduino ports. If detection selects the wrong
device, pass an explicit port with `--port`.

## Run real telemetry

Use three terminals. Activate `.venv` in each terminal on Linux/macOS, or run
`.\.venv\Scripts\Activate.ps1` in each PowerShell terminal on Windows.

### Terminal 1: real WebSocket relay

Linux/macOS/Windows:

```text
python telemetry_bridge.py --real
```

The relay listens on `ws://localhost:8765`. Do not use
`python telemetry_bridge.py` for a hardware run; that command starts mock data.

### Terminal 2: Arduino acquisition and DSP

Automatic port detection:

```text
python -u attention_feed_arduino.py
```

Explicit port examples:

```bash
# Linux
python -u attention_feed_arduino.py --port /dev/ttyACM0

# macOS
python -u attention_feed_arduino.py --port /dev/cu.usbmodem14101
```

```powershell
# Windows PowerShell
python -u attention_feed_arduino.py --port COM3
```

The same override can be supplied without changing the command:

```bash
export CORTICOWAVES_ARDUINO_PORT=/dev/ttyACM0
python -u attention_feed_arduino.py
```

```powershell
$env:CORTICOWAVES_ARDUINO_PORT = "COM3"
python -u attention_feed_arduino.py
```

There is no separate eyes-open/eyes-closed session and no hardcoded baseline.
The first five seconds of raw Beta/Alpha ratios are used only to seed the
running mean and standard deviation; the exported drive is neutral during
this warm-up. Afterward, the mean and variance adapt continuously with an
EWMA time constant of 30 seconds at the 10 Hz DSP update rate.
The 1.5-second Welch window and short ratio smoother reduce spectral-window
jitter before the live adaptive normalization without introducing a static
baseline.

## Live latency budget

With an Arduino Uno sampling at 100 Hz, the first meaningful rocket response
is approximately **0.9-1.8 seconds** after a sustained EEG change. A mostly
settled response takes approximately **2.5-4 seconds** because the system
intentionally smooths the spectral ratio and rocket motion:

| Stage | Typical contribution |
| --- | ---: |
| Arduino ADC sample and Firmata/USB delivery | 10-30 ms |
| Rolling Welch feature window | 0.75 s effective response, up to 1.5 s to fully replace old data |
| DSP update scheduling | 0-100 ms |
| Local WebSocket bridge and browser delivery | usually under 20 ms |
| Browser frame scheduling | 0-17 ms |
| Ratio smoothing and rocket interpolation | approximately 0.95 s for first response, up to 2.85 s to mostly settle |

The first-response estimate is the 0.75-second effective spectral window plus
the 0.4-second ratio smoother and 0.55-second rocket interpolation time
constants, with transport and scheduling overhead. The settled estimate uses
roughly two to three time constants for the smoothing stages plus the
1.5-second rolling window. The Arduino's 10 ms sample interval is therefore
not the system's total latency. The serial link and bridge are comparatively
small; the rolling spectral window and intentional smoothing dominate the
response.

The DSP calculation already runs independently of the Firmata callback and
WebSocket publisher, so multiprocessing would not reduce this response time:
it would only move the approximately 0.15 ms numerical calculation to another
worker while adding IPC overhead. The shorter Welch window is the effective
latency reduction. It provides approximately 0.67 Hz frequency-bin spacing
instead of 0.33 Hz, which remains suitable for the configured alpha and beta
bands but is less noise-averaged than the previous window.

### Terminal 3: Astro dashboard

From the repository root:

```bash
cd dashboard
npm run dev -- --host localhost --port 4321
```

Open the URL Astro prints, normally `http://localhost:4321`.

The dashboard contains the live telemetry graph, attention readout, and
attention-controlled browser rocket game. The rocket starts with **START
MISSION** and can be relaunched with **RESTART MISSION** after a collision.

## Verify the Arduino port

Linux/macOS:

```bash
python -m serial.tools.list_ports -v
```

Windows PowerShell:

```powershell
python -m serial.tools.list_ports -v
```

Expected examples:

```text
/dev/ttyACM0
/dev/cu.usbmodem14101
COM3
```

After unplugging and reconnecting the Arduino, stop and restart
`attention_feed_arduino.py`; Firmata does not automatically reinitialize a
physically disconnected board.

## Stop and restart services

Stop each foreground process with `Ctrl+C`. Restart in this order:

1. `python telemetry_bridge.py --real`
2. `python -u attention_feed_arduino.py`
3. `cd dashboard; npm run dev -- --host localhost --port 4321`

If port `8765` is already in use:

Linux/macOS:

```bash
ss -ltnp | grep ':8765'       # Linux
lsof -nP -iTCP:8765 -sTCP:LISTEN  # macOS
kill <PID>
```

Windows PowerShell:

```powershell
Get-NetTCPConnection -LocalPort 8765
Stop-Process -Id <PID>
```

If Astro moves to port `4322`, an older Astro process is using `4321`. Close
the old process or open the URL Astro reports.

## Mock telemetry

Use mock telemetry only when the Arduino is disconnected:

```text
python telemetry_bridge.py
```

Mock packets are marked `source: "mock"`. Real packets are marked
`source: "arduino"`. If the dashboard shows mock data during a hardware run,
stop the mock bridge and start `python telemetry_bridge.py --real`.

## Raw Arduino stream

To inspect normalized values, volts, and reconstructed 10-bit ADC counts:

```text
python hardware/arduino_raw_data.py
```

Explicit ports:

```text
python hardware/arduino_raw_data.py --port COM3
python hardware/arduino_raw_data.py --port /dev/ttyACM0
```

## Standalone desktop rocket

The original Pygame prototype remains available separately from the browser
dashboard:

```text
python rocket_game.py
```

It uses local mouse/trackpad input. The browser game uses the live attention
metric instead.

## Project layout

- `corticowaves_dsp.py` — adaptive EWMA Z-score engine, Welch band-power
  calculation, and raw Beta/Alpha ratio helpers.
- `attention_feed_arduino.py` — Arduino acquisition, filtering, Welch PSD,
  adaptive Z-score normalization, and telemetry.
- `hardware/arduino_raw_data.py` — portable raw Arduino stream inspector.
- `telemetry_bridge.py` — local mock or real WebSocket relay.
- `dashboard/` — Astro/Tailwind dashboard and browser rocket game.
- `rocket_game.py` — standalone Pygame prototype.
- `docs/architecture/corticowaves_flowchart.dot` — Graphviz source.
- `docs/architecture/corticowaves_flowchart.png` — rendered flowchart.

## Troubleshooting

### `ModuleNotFoundError`

Activate the virtual environment and reinstall:

```text
python -m pip install -r requirements.txt
```

### Arduino port not found

Confirm the board appears in Arduino IDE, close Serial Monitor, upload
`StandardFirmata`, and run `python -m serial.tools.list_ports -v`. Then pass
the exact port with `--port`.

### `Permission denied` on Linux

Add the user to `dialout`, log out/in, and reconnect the Arduino:

```bash
sudo usermod -aG dialout "$USER"
```

### `address already in use`

Another bridge or dashboard is still running. Use the platform-specific port
commands above, stop the old process, and restart in the documented order.

### Dashboard shows a neutral attention value at startup

The adaptive engine intentionally emits `z_score: 0.0` and
`attention_metric: 0.5` during its five-second warm-up. After warm-up, inspect
`attention_ratio`, `z_score`, `running_mean`, and `running_std` in the live
telemetry packets.
