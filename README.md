# CorticoWaves

CorticoWaves reads EEG data from either an Arduino Uno or an ESP32 with an
ADS1115 converter, calculates a live Beta/Alpha attention metric, and sends
the result to a local Astro dashboard and rocket game.

## How the system works

```text
Arduino or ESP32 + ADS1115
  -> serial acquisition
  -> 0.5-30 Hz Arduino / 0.5-50 Hz ESP32 filter
  -> Welch PSD and Beta/Alpha ratio
  -> adaptive Z-score and sigmoid attention metric [0, 1]
  -> WebSocket relay at ws://localhost:8765
  -> Astro dashboard
```

The ESP32 path uses 250 samples/second and 115200 baud. The Arduino path uses
100 samples/second through StandardFirmata. The adaptive engine warms up for
five seconds and then continuously updates its mean and variance; no
eyes-open/eyes-closed calibration is required.

## Requirements

- Python 3.10+
- Node.js 20+ and npm
- Arduino IDE
- BioAmp EXG Pill and electrodes
- USB data cable
- Either:
  - Arduino Uno with the `StandardFirmata` example, or
  - ESP32, ADS1115, and the firmware in
    `hardware/esp32_ads1115/esp32_ads1115.ino`

## Install

### Linux and macOS

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cd dashboard
npm install
cd ..
```

On Linux, grant the current user access to USB serial devices, then log out
and back in:

```bash
sudo usermod -aG dialout "$USER"
```

### Windows PowerShell

Install Python and Node.js, then run:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cd dashboard
npm install
cd ..
```

If activation is blocked:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## Hardware setup

### Arduino Uno

1. Open Arduino IDE.
2. Open **File > Examples > Firmata > StandardFirmata**.
3. Select the Arduino board and USB port.
4. Upload the example.
5. Close Serial Monitor before starting Python.

Find the serial port with:

```bash
python -m serial.tools.list_ports -v
```

Typical ports are `/dev/ttyACM0`, `/dev/ttyUSB0`, `/dev/cu.usbmodem*`, or
`COM3`.

### ESP32 and ADS1115

Use this wiring:

| BioAmp EXG Pill | ADS1115 | ESP32 |
| --- | --- | --- |
| VCC | VDD | 3V3 |
| GND | GND | GND |
| OUT | A0 | — |
| — | SDA | GPIO 21 |
| — | SCL | GPIO 22 |
| — | ADDR | GND |

This gives the ADS1115 address `0x48`. The configurable firmware values are
at the top of `hardware/esp32_ads1115/esp32_ads1115.ino`:

```cpp
I2C_SDA_PIN
I2C_SCL_PIN
ADS1115_I2C_ADDRESS
ADS1115_CHANNEL
SAMPLE_RATE_HZ
SERIAL_BAUD
ADS1115_GAIN
```

In Arduino IDE:

1. Install the ESP32 board package.
2. Install the **Adafruit ADS1X15** library.
3. Open the ESP32 sketch.
4. Select the correct ESP32 board and port.
5. Upload the sketch.
6. Open Serial Monitor at **115200 baud** and press **EN/RST**.

Expected output:

```text
BOOT,CORTICOWAVES_ESP32
ADS1115,CONNECTED
READY,250,A0,2/3
S,0,...
S,1,...
```

If the ADS1115 is not detected, the firmware prints:

```text
ERROR,ADS1115_NOT_FOUND
```

Close Serial Monitor before starting Python because only one process can own
the serial port.

## Run the application

Open three terminals. Activate `.venv` in each terminal.

### Terminal 1: WebSocket relay

For real hardware:

```bash
python telemetry_bridge.py --real
```

The relay listens on `ws://localhost:8765`.

For mock data without hardware:

```bash
python telemetry_bridge.py
```

### Terminal 2: acquisition and DSP

Arduino with automatic port detection:

```bash
python -u attention_feed_arduino.py --backend arduino
```

Arduino with an explicit port:

```bash
python -u attention_feed_arduino.py --backend arduino --port /dev/ttyACM0
```

Windows example:

```powershell
python -u attention_feed_arduino.py --backend arduino --port COM3
```

ESP32 with an explicit port:

```bash
python -u attention_feed_arduino.py \
  --backend esp32_ads1115 \
  --port /dev/ttyUSB0 \
  --baudrate 115200 \
  --sample-rate 250
```

Windows example:

```powershell
python -u attention_feed_arduino.py `
  --backend esp32_ads1115 `
  --port COM5 `
  --baudrate 115200 `
  --sample-rate 250
```

### Terminal 3: dashboard

```bash
cd dashboard
npm run dev -- --host localhost --port 4321
```

Open `http://localhost:4321`.

The dashboard displays the live signal, attention metric, connection state,
and rocket game. Press **START MISSION** or **Space** to begin. Press the
pause button or **Space** again to pause and resume.

## Useful commands

List serial devices:

```bash
python -m serial.tools.list_ports -v
```

Inspect Arduino samples:

```bash
python hardware/arduino_raw_data.py --port /dev/ttyACM0
```

Run the standalone desktop prototype:

```bash
python rocket_game.py
```

Stop each service with `Ctrl+C`. Start them again in this order:

1. `python telemetry_bridge.py --real`
2. `python -u attention_feed_arduino.py ...`
3. `cd dashboard && npm run dev -- --host localhost --port 4321`

## Troubleshooting

### Serial port is busy

Close Arduino Serial Monitor and Serial Plotter. Stop any other acquisition
process using the same port, then retry.

### No ESP32 output

Confirm that the correct board and port are selected, the monitor is set to
115200 baud, and the ESP32 was reset with **EN/RST**. Check 3V3, GND, SDA,
SCL, ADS1115 address `0x48`, and the Adafruit ADS1X15 library.

### `ADS1115_NOT_FOUND`

Check the ADS1115 power and ground connections, SDA/SCL pins, ADDR wiring,
and that the BioAmp output is connected to A0.

### No samples received by Python

Check the selected port with `python -m serial.tools.list_ports -v`, close
Serial Monitor, and ensure the Python baud rate matches the firmware:
`115200` for the provided ESP32 sketch.

### Dashboard is offline

Ensure the real relay is running on port `8765`, then open the dashboard on
the same computer. The dashboard connects to `ws://localhost:8765`.

## Project files

- `attention_feed_arduino.py` — acquisition, filtering, DSP, and telemetry.
- `corticowaves_dsp.py` — Welch PSD, Beta/Alpha ratio, and adaptive Z-score.
- `hardware/signal_sources.py` — Arduino and ESP32 serial adapters.
- `hardware/esp32_ads1115/esp32_ads1115.ino` — ESP32 firmware.
- `telemetry_bridge.py` — local WebSocket relay.
- `dashboard/` — Astro/Tailwind dashboard and browser game.
- `hardware/arduino_raw_data.py` — raw Arduino inspection utility.
- `docs/architecture/` — Graphviz flowchart source and rendered image.
