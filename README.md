# CorticoWaves

CorticoWaves is a corticothalamic neural field oscillation project. The current
prototype implements the first two stages in the architecture: Arduino
Firmata acquisition from a BioAmp EXG Pill and a Python DSP engine that
calculates the beta/alpha attention metric without an ADS1115 converter.

## Project layout

- `hardware/arduino_raw_data.py` streams raw Arduino samples as normalized
  values, volts, and reconstructed 10-bit ADC counts.
- `attention_feed_arduino.py` buffers the Arduino stream and calculates alpha
  and beta bandpower with Welch PSD.
- `docs/architecture/corticowaves_flowchart.dot` is the source Graphviz
  flowchart; `corticowaves_flowchart.png` is the rendered reference image.
- `dashboard/` is the Astro/Tailwind dashboard for the stage-3 WebSocket
  bridge and future WebGL stages.
- `telemetry_bridge.py` provides the local stage-3 WebSocket bridge. It emits
  mock telemetry until the Arduino/DSP pipeline is connected. Mock packets
  run at 100 Hz and are explicitly marked with `source: "mock"`.

## Dashboard setup

The existing Astro/Tailwind dashboard can be run with:

```bash
cd dashboard
npm install
npm run dev
```

It serves at `http://localhost:4321` and connects to `ws://localhost:8765`.

## Real Arduino telemetry

Use three terminals. Do not run `python telemetry_bridge.py` for hardware; that
command starts the synthetic mock stream.

In **Terminal 1**, start the real-hardware relay:

```bash
python -m pip install -r requirements.txt
python telemetry_bridge.py --real
```

In **Terminal 2**, start the Arduino/DSP publisher:

```bash
python -u attention_feed_arduino.py
```

Wait for:

```text
[*] Auto-detected Arduino on port: /dev/ttyACM0
[*] Firmata connection established.
```

After about two seconds, the terminal should print changing alpha, beta, and
attention values. In **Terminal 3**, start Astro:

```bash
npm --prefix dashboard run dev -- --host localhost --port 4321
```

Open the URL Astro prints, normally `http://localhost:4321`. The dashboard
feed must show `source: arduino`. If it shows `source: mock`, stop the bridge
with `Ctrl-C` and restart it using `python telemetry_bridge.py --real`.

If the Arduino is unplugged and reconnected, stop the Arduino publisher with
`Ctrl-C`, wait for `/dev/ttyACM0` to reappear, then restart Terminal 2.
Firmata does not automatically reinitialize a physically disconnected board.

The Arduino callback keeps the full 100 Hz filtered stream locally for DSP,
while a dedicated `telemetry-publisher` thread sends a 20 Hz average of the
newest filtered samples for visualization along with the latest DSP attention
result. A
streaming 0.5-30 Hz Butterworth band-pass removes baseline drift and 50 Hz
mains content before DSP and transport. There is no network queue of historical
samples, so stopping the bridge cannot create a stale-data burst when it
reconnects. WebSocket latency cannot block serial acquisition or PSD
calculation.

The attention metric intentionally uses the full-rate 100 Hz filtered ring
buffer, not the lower-resolution graph average. The graph packet includes
`display_averaged` and `samples_averaged` so this distinction is visible.

## Mock telemetry

Only use this when the Arduino is disconnected:

```bash
python telemetry_bridge.py
```

Mock packets run at 100 Hz and are marked `source: "mock"`.

## Manual relay input

To relay newline-delimited JSON from another stage-2 process:

```bash
python telemetry_bridge.py --stdin --keep-open
```
