import time
import argparse
import os
from pyfirmata2 import Arduino

start_time = None

def bioamp_callback(data):
    """Callback function triggered automatically when new sample arrives."""
    global start_time
    if data is not None:
        if start_time is None:
            start_time = time.time()
            
        elapsed_time = time.time() - start_time
        voltage = data * 5.0            # Scaled to 5V reference
        adc_count = int(data * 1023.0)  # Reconstructed 10-bit integer ADC value
        
        print(f"{elapsed_time:8.2f}s | {data:20.4f} | {voltage:10.3f} V | {adc_count:18d}")

def find_arduino_port():
    import serial.tools.list_ports

    for port in serial.tools.list_ports.comports():
        description = port.description or ""
        if (
            "Arduino" in description
            or "ttyACM" in port.device
            or "ttyUSB" in port.device
            or port.device.startswith("COM")
            or "usbmodem" in port.device
            or "usbserial" in port.device
        ):
            return port.device
    return None


def main(port_override=None):
    port = port_override or os.environ.get("CORTICOWAVES_ARDUINO_PORT") or find_arduino_port()
    if not port:
        raise RuntimeError(
            "Arduino port not found. Pass --port COM3, /dev/ttyACM0, "
            "or /dev/cu.usbmodem*."
        )

    try:
        board = Arduino(port)
        print(f"Successfully connected to Arduino on {port}")

        # Set hardware sampling interval to 10 ms (100 Hz)
        board.samplingOn(10)

        # Configure Analog Pin 0 as Input
        bioamp_pin = board.get_pin('a:0:i')
        
        # Register the callback and start listening
        bioamp_pin.register_callback(bioamp_callback)
        bioamp_pin.enable_reporting()

        print("\n--- Streaming Raw BioAmp EXG Data (Callback Mode) ---")
        print("Time (s)  | Normalized (0.0-1.0) | Voltage (V) | 10-bit ADC (0-1023)")
        print("-" * 65)

        # Keep main thread alive while callback handles output
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nData capture stopped by user.")
    except Exception as e:
        print(f"\nError encountered: {e}")
    finally:
        if 'board' in locals():
            board.exit()
            print("Arduino serial connection closed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stream raw Arduino BioAmp samples.")
    parser.add_argument("--port", default=None, help="Arduino serial port override")
    args = parser.parse_args()
    main(args.port)