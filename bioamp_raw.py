import time
from pyfirmata2 import Arduino

# Specify port or use '/dev/ttyACM0' / 'COM3'
PORT = '/dev/ttyACM0' 

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

def main():
    try:
        board = Arduino(PORT)
        print(f"Successfully connected to Arduino on {PORT}")

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
    main()