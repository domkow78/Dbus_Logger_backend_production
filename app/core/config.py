"""
Konfiguracja aplikacji do logowania komunikacji UART.
"""

import os
import socket

# Detekcja cykli: CMD + DATA
# START: CMD=1001 (0x1001), DATA=01 00
# END:   CMD=1001 (0x1001), DATA=03 00
CYCLE_CMD = bytes([0x10, 0x01])           # Wspólna komenda ID: 1001
CYCLE_START_DATA = bytes([0x01, 0x00])    # DATA dla START cyklu
CYCLE_END_DATA = bytes([0x03, 0x00])      # DATA dla END cyklu

# ==============================================================================
# STATION IDENTIFICATION
# ==============================================================================

def get_station_id():
    """
    Pobiera ID stanowiska z zmiennej środowiskowej lub używa hostname jako fallback.
    
    Returns:
        str: ID stanowiska
    """
    return os.getenv("STATION_ID", socket.gethostname())


def get_local_ip():
    """
    Pobiera lokalny adres IP maszyny.
    
    Returns:
        str: Adres IP lub '127.0.0.1' jeśli nie można ustalić
    """
    try:
        # Trik: połącz się do zewnętrznego IP (nie wysyła pakietów)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

# Ścieżki do katalogów
LOGS_DIR = "logs/"
APP_LOG_DIR = "app_logs/"

# Plik persystencji licznika cykli
COUNTER_FILE = "logs/.cycle_counter"

# Timeout przerwania połączenia (sekundy)
INTERRUPTION_TIMEOUT = 5.0

# Mechanizm automatycznego wznawiania połączenia
RECONNECT_ENABLED = True          # Czy włączyć automatyczne wznawianie
RECONNECT_DELAY = 2.0             # Opóźnienie między próbami połączenia (sekundy)
RECONNECT_MAX_ATTEMPTS = 0        # Max liczba prób (0 = nieskończone próby)
RECONNECT_BACKOFF = True          # Czy zwiększać opóźnienie przy kolejnych próbach
RECONNECT_MAX_DELAY = 30.0        # Maksymalne opóźnienie między próbami (sekundy)

# Format timestampu
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S.%f"  # używamy [:-3] dla milisekund

# Rotacja logów aplikacyjnych (dni)
APP_LOG_RETENTION_DAYS = 1
# Rotacja logów cykli (logs/) (dni)
LOGS_RETENTION_DAYS = 7  # domyślnie 7 dni, zmień wg potrzeb

# ==============================================================================
# KONFIGURACJA UART
# ==============================================================================

import platform

def detect_os():
    """
    Wykrywa system operacyjny.
    
    Returns:
        str: 'windows', 'linux', lub 'unknown'
    """
    system = platform.system()
    if system == "Windows":
        return "windows"
    elif system == "Linux":
        return "linux"
    else:
        return "unknown"


# Wykryj system
CURRENT_OS = detect_os()

# Domyślne porty szeregowe dla różnych systemów
DEFAULT_PORTS = {
    'windows': 'COM5',
    'linux': '/dev/ttyUSB0',      # Raspberry Pi, adapter USB
    'unknown': 'COM1'
}

# Domyślny port dla aktualnego systemu
DEFAULT_PORT = DEFAULT_PORTS.get(CURRENT_OS, 'COM1')

# Alternatywne porty (sugestie)
COMMON_PORTS = {
    'windows': ['COM1', 'COM3', 'COM4', 'COM5'],
    'linux': [
        '/dev/ttyUSB0',    # USB-UART adapter
        '/dev/ttyUSB1',
        '/dev/ttyAMA0',    # Raspberry Pi hardware UART
        '/dev/ttyS0',      # Standard serial port
        '/dev/serial0',    # Raspberry Pi symlink
    ],
    'unknown': ['COM1']
}

# Domyślne parametry UART
DEFAULT_BAUDRATE = 9600
DEFAULT_BYTESIZE = 8
DEFAULT_PARITY = 'N'  # 'N'=None, 'E'=Even, 'O'=Odd
DEFAULT_STOPBITS = 1
DEFAULT_TIMEOUT = 1.0  # sekundy

# Popularne baudrate
COMMON_BAUDRATES = [
    9600,
    19200,
    38400,
    57600,
    115200,
    230400,
    460800,
]

# Mapowanie parity dla pyserial
def get_parity_constant(parity_char: str):
    """
    Konwertuje znak parity na stałą pyserial.
    
    Args:
        parity_char: 'N', 'E', lub 'O'
    
    Returns:
        Stała pyserial.PARITY_*
    """
    import serial
    parity_map = {
        'N': serial.PARITY_NONE,
        'E': serial.PARITY_EVEN,
        'O': serial.PARITY_ODD,
        'M': serial.PARITY_MARK,
        'S': serial.PARITY_SPACE,
    }
    return parity_map.get(parity_char.upper(), serial.PARITY_NONE)


# ==============================================================================
# HELPER: Lista dostępnych portów
# ==============================================================================

def list_available_ports():
    """
    Zwraca listę dostępnych portów szeregowych w systemie.
    
    Returns:
        list: Lista nazw portów (np. ['COM3', 'COM5'])
    """
    try:
        import serial.tools.list_ports
        ports = serial.tools.list_ports.comports()
        return [port.device for port in ports]
    except ImportError:
        # Jeśli pyserial nie zainstalowane, zwróć domyślne
        return COMMON_PORTS.get(CURRENT_OS, [])