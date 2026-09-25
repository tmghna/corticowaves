import sys
import time
import collections
import threading
import numpy as np
from scipy.signal import welch
import serial.tools.list_ports
from pyfirmata2 import Arduino

# ==========================================
# SYSTEM PARAMETERS
# ==========================================
FS = 100                  # Hardware sampling rate via Firmata (10ms = 100 Hz)
WINDOW_SEC = 2.0          # Rolling window length for PSD calculation
BUFFER_SIZE = int(FS * WINDOW_SEC)
REFRESH_RATE = 0.1        # Update terminal output every 0.1 seconds (10 Hz)

# Thread-safe rolling buffer for incoming analog samples
signal_buffer = collections.deque(maxlen=BUFFER_SIZE)
buffer_lock = threading.Lock()

# ==========================================
# CROSS-PLATFORM PORT DETECTION
# ==========================================
def find_arduino_port():
    """Automatically detects the Arduino serial port across Linux, Windows, and Mac."""
    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        # Match common identifiers for standard Arduino Uno
        if 'Arduino' in p.description or 'ttyACM' in p.device or 'ttyUSB' in p.device:
            return p.device
    
    # Fallback for Windows if generic descriptor is used
    for p in ports:
        if p.device.startswith('COM'):
            return p.device
            
    return None

# ==========================================
# FIRMATA HARDWARE CALLBACK
# ==========================================
def bioamp_callback(data):
    """Event-driven callback triggered by pyfirmata2 every 10ms."""
    if data is not None:
        # Scale Firmata's normalized 0.0-1.0 float to 0-5V physical voltage
        voltage = data * 5.0
        
        # Thread-safe append to the rolling deque
        with buffer_lock:
            signal_buffer.append(voltage)

# ==========================================
# DIGITAL SIGNAL PROCESSING (DSP) ENGINE
# ==========================================
def calculate_attention_metric(signal_array, fs):
    """Extracts Alpha and Beta bandpower from raw voltage to calculate Attention Index."""
    # 1. DC Offset Removal (Zero-mean the signal to remove 0 Hz spike)
    signal = signal_array - np.mean(signal_array)
    
    # 2. Welch's Power Spectral Density Estimation
    # nperseg limits window length to improve noise averaging
    freqs, psd = welch(signal, fs=fs, nperseg=min(128, len(signal)))
    
    # 3. Frequency Band Masking
    alpha_mask = (freqs >= 8.0) & (freqs <= 12.0)
    beta_mask = (freqs >= 13.0) & (freqs <= 30.0)
    
    # 4. Numerical Integration (Area under the PSD curve)
    # Epsilon (1e-6) added to Alpha to strictly prevent division-by-zero
    p_alpha = np.trapezoid(psd[alpha_mask], freqs[alpha_mask]) + 1e-6
    p_beta = np.trapezoid(psd[beta_mask], freqs[beta_mask])
    
    # 5. Raw Attention Index
    attention_ratio = p_beta / p_alpha
    
    return p_alpha, p_beta, attention_ratio

# ==========================================
# MAIN EXECUTION THREAD
# ==========================================
def main():
    port = find_arduino_port()
    if not port:
        print("Error: Could not auto-detect Arduino port. Check USB connection.")
        sys.exit(1)
        
    print(f"[*] Auto-detected Arduino on port: {port}")
    
    try:
        board = Arduino(port)
        print("[*] Firmata connection established.")
        
        # Configure hardware timer to sample every 10ms (100 Hz)
        board.samplingOn(10)
        
        # Initialize Analog Pin 0 as Input
        bioamp_pin = board.get_pin('a:0:i')
        bioamp_pin.register_callback(bioamp_callback)
        bioamp_pin.enable_reporting()
        
        print(f"[*] Buffering {WINDOW_SEC} seconds of BioAmp EXG data...")
        time.sleep(WINDOW_SEC)
        
        print("\n" + "="*70)
        print(f"{'Alpha (8-12 Hz)':<20} | {'Beta (13-30 Hz)':<20} | {'Attention (Beta/Alpha)':<25}")
        print("="*70)
        
        while True:
            with buffer_lock:
                current_length = len(signal_buffer)
                if current_length == BUFFER_SIZE:
                    # Create a static snapshot of the array for mathematical processing
                    signal_snapshot = np.array(signal_buffer)
                else:
                    signal_snapshot = None
            
            if signal_snapshot is not None:
                p_alpha, p_beta, attention = calculate_attention_metric(signal_snapshot, FS)
                
                # Format output with fixed decimal widths to prevent terminal jitter
                sys.stdout.write(f"\r{p_alpha:<20.6f} | {p_beta:<20.6f} | {attention:<25.4f}")
                sys.stdout.flush()
                
            # Lock the DSP processing loop to the target refresh rate
            time.sleep(REFRESH_RATE)
            
    except KeyboardInterrupt:
        print("\n\n[*] CorticoWaves DSP pipeline stopped by user.")
    except Exception as e:
        print(f"\n[!] Unexpected Error: {e}")
    finally:
        if 'board' in locals():
            board.exit()
            print("[*] Serial interface closed safely.")

if __name__ == "__main__":
    main()