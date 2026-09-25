"""Local stage-3 WebSocket bridge for the CorticoWaves dashboard.

The default mock stream keeps the dashboard usable before Arduino hardware and
the stage-2 DSP process are connected. Pass --stdin to broadcast newline-
delimited JSON packets from another process instead.
"""

import argparse
import asyncio
import json
import math
import random
import sys
import time

import websockets
from websockets.exceptions import ConnectionClosed, ConnectionClosedError, ConnectionClosedOK


CLIENTS = set()


async def dashboard_client(websocket):
    CLIENTS.add(websocket)
    try:
        try:
            async for message in websocket:
                try:
                    packet = json.loads(message)
                except json.JSONDecodeError:
                    print("[bridge] ignored non-JSON WebSocket packet", file=sys.stderr)
                    continue
                await broadcast(packet, exclude=websocket)
        except (ConnectionClosed, ConnectionClosedError, ConnectionClosedOK, TimeoutError):
            # Browser reloads and publisher restarts are normal during local
            # development and must not terminate the bridge.
            pass
    finally:
        CLIENTS.discard(websocket)


async def broadcast(packet, exclude=None):
    if not CLIENTS:
        return
    message = json.dumps(packet)
    recipients = tuple(client for client in CLIENTS if client is not exclude)
    results = await asyncio.gather(
        *(client.send(message) for client in recipients),
        return_exceptions=True,
    )
    for client, result in zip(recipients, results):
        if isinstance(result, (ConnectionClosed, ConnectionClosedError, ConnectionClosedOK, TimeoutError)):
            CLIENTS.discard(client)


async def mock_stream(rate_hz):
    started = time.monotonic()
    sample_index = 0
    interval = 1 / rate_hz
    next_sample = started
    while True:
        elapsed = time.monotonic() - started
        # A visible 10 Hz alpha component plus an 18 Hz beta component makes
        # the development stream resemble the 100 Hz Arduino sample cadence.
        voltage = (
            2.5
            + 0.08 * math.sin(elapsed * 2 * math.pi * 10)
            + 0.035 * math.sin(elapsed * 2 * math.pi * 18)
            + random.uniform(-0.015, 0.015)
        )
        attention = 0.5 + 0.3 * math.sin(elapsed * 1.2)
        await broadcast(
            {
                "timestamp": time.time(),
                "raw": round(voltage, 4),
                "attention": round(max(0.0, min(1.0, attention)), 4),
                "source": "mock",
                "sample_index": sample_index,
            }
        )
        sample_index += 1
        next_sample += interval
        await asyncio.sleep(max(0, next_sample - time.monotonic()))


async def stdin_stream(keep_open):
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            if not keep_open:
                return
            await asyncio.sleep(0.25)
            continue
        try:
            packet = json.loads(line)
        except json.JSONDecodeError:
            print("[bridge] ignored non-JSON stdin packet", file=sys.stderr)
            continue
        await broadcast(packet)


async def run(args):
    async with websockets.serve(
        dashboard_client,
        args.host,
        args.port,
        ping_interval=20,
        ping_timeout=10,
        close_timeout=2,
    ):
        mode = "mock" if args.mock else "real"
        print(f"[bridge] WebSocket telemetry bridge listening on ws://{args.host}:{args.port} ({mode})")
        if args.mock:
            stream = mock_stream(args.mock_rate)
        elif args.keep_open:
            # The Arduino publisher connects as a WebSocket client; it doesn't
            # need stdin. Waiting on an event keeps the bridge alive even when
            # launched from a terminal with no persistent stdin pipe.
            stream = asyncio.Event().wait()
        else:
            stream = stdin_stream(False)
        await stream


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--mock-rate", type=float, default=100, help="mock samples per second")
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="run as a persistent WebSocket server for the Arduino publisher",
    )
    parser.add_argument(
        "--real",
        action="store_true",
        help="run as a persistent real-hardware relay; equivalent to --stdin --keep-open",
    )
    parser.add_argument(
        "--stdin",
        dest="mock",
        action="store_false",
        help="broadcast newline-delimited JSON packets read from stdin",
    )
    parser.set_defaults(mock=True)
    args = parser.parse_args()
    if args.real:
        args.mock = False
        args.keep_open = True
    return args


if __name__ == "__main__":
    try:
        asyncio.run(run(parse_args()))
    except KeyboardInterrupt:
        print("\n[bridge] stopped")
