# Core Module - UART Logger

## 📋 Przegląd

Moduł `core` zawiera rdzenną logikę aplikacji do logowania komunikacji UART z automatyczną detekcją cykli. 

**Architektura bezramowa (framework-agnostic)** - czysta logika biznesowa bez zależności od API czy GUI.

**Zastosowania:**
- 🖥️ **Backend API** - Uruchamiane na Raspberry Pi poprzez `start_backend.py`
- 🖥️ **Standalone** - Demo w `demo_core_app.py` (bez FastAPI/NiceGUI)
- 🧪 **Testy** - `test_core_app.py`, `test_uart.py`

## 📦 Struktura modułu

```
core/
├── config.py        # Konfiguracja aplikacji i UART
├── uart.py          # Niskopoziomowa obsługa UART
├── core_app.py      # Główna logika aplikacji
└── README.md        # Ten plik
```

---

## 🔧 config.py

### Opis
Centralny punkt konfiguracji aplikacji. Zawiera wszystkie parametry UART, ścieżki do katalogów, ustawienia detekcji cykli i funkcje pomocnicze.

### ⚙️ Funkcje identyfikacji stacji

**Nowość w architekturze multi-station:**

```python
def get_station_id() -> str:
    """Identyfikator stacji (STATION_ID env lub hostname)"""
    return os.getenv('STATION_ID') or socket.gethostname()

def get_local_ip() -> str:
    """Adres IP w sieci LAN (auto-detect)"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))  # Nie wysyła danych
    ip = s.getsockname()[0]
    s.close()
    return ip
```

**Zastosowanie:**
- `GET /health` endpoint - zwraca `station_id` i `ip_address`
- mDNS auto-discovery - publikuje usługę `{station_id}._uart-logger._tcp.local.`
- Identyfikacja wielu Raspberry Pi w sieci LAN

**Konfiguracja:**
```bash
# Raspberry Pi - systemd service
Environment="STATION_ID=UART-RPI-001"

# Ręczne uruchomienie
export STATION_ID="UART-RPI-LAB"
python start_backend.py
```

### Główne sekcje

#### 1️⃣ Detekcja cykli
```python
CYCLE_CMD = bytes([0x10, 0x01])           # Komenda ID: 1001
CYCLE_START_DATA = bytes([0x01, 0x00])    # DATA dla START cyklu
CYCLE_END_DATA = bytes([0x03, 0x00])      # DATA dla END cyklu
```

**Jak działa:**
- Cykl START: `CMD=1001`, `DATA=01 00`
- Cykl END: `CMD=1001`, `DATA=03 00`

#### 2️⃣ Ścieżki i pliki
```python
LOGS_DIR = "logs/"                # Katalog logów cykli
APP_LOG_DIR = "app_logs/"         # Katalog logów aplikacyjnych
COUNTER_FILE = "logs/.cycle_counter"  # Persystentny licznik cykli
```

#### 3️⃣ Timeouty i formaty
```python
INTERRUPTION_TIMEOUT = 5.0        # Timeout przerwania połączenia (s)
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S.%f"  # Format timestampu (ms)
APP_LOG_RETENTION_DAYS = 1        # Rotacja logów aplikacyjnych
```

#### 4️⃣ Konfiguracja UART
```python
DEFAULT_BAUDRATE = 9600
DEFAULT_BYTESIZE = 8
DEFAULT_PARITY = 'N'    # N=None, E=Even, O=Odd
DEFAULT_STOPBITS = 1
DEFAULT_TIMEOUT = 1.0   # sekundy
```

**Auto-detekcja systemu:**
- Windows: `COM5` (domyślnie)
- Linux: `/dev/ttyAMA0` (domyślnie – GPIO UART, BT wyłączony)

### Funkcje pomocnicze

| Funkcja | Opis |
|---------|------|
| `detect_os()` | Wykrywa system operacyjny (windows/linux) |
| `get_parity_constant(char)` | Konwertuje znak parity ('N','E','O') na stałą pyserial |
| `list_available_ports()` | Listuje dostępne porty szeregowe w systemie |

### Popularne konfiguracje baudrate
```python
COMMON_BAUDRATES = [9600, 19200, 38400, 57600, 115200, 230400, 460800]
```

---

## 📡 uart.py

### Opis
Niskopoziomowa obsługa komunikacji UART. Implementuje protokół transmisji ramek z CRC16-XMODEM, wykrywanie idle gaps i parsowanie transakcji.

### Klasy

#### `AckType` (Enum)
Typy potwierdzenia ACK.

```python
AckType.OK    = 0x0A  # Potwierdzenie OK
AckType.BUSY  = 0x03  # Urządzenie zajęte
AckType.WRONG = 0x07  # Błąd
```

**Metody:**
- `from_byte(byte: int)` - Dekoduje ACK z bajtu (sprawdza dolny nibble)

---

#### `SerialPort`
Rozszerzona klasa `serial.Serial` z logowaniem i obsługą błędów.

**Konstruktor:**
```python
SerialPort(
    port,                          # 'COM3' lub '/dev/ttyAMA0'
    baudrate=9600,
    bytesize=8,
    parity=serial.PARITY_NONE,
    stopbits=1,
    timeout=1
)
```

**Metody:**
- `open_port()` - Otwiera port z obsługą wyjątków
- `close()` - Zamyka port z logowaniem

---

#### `CRC16XModem`
Obliczanie sumy kontrolnej CRC16-XMODEM.

**Metoda statyczna:**
```python
CRC16XModem.calculate(data: bytes) -> int
```

**Parametry CRC:**
- Polynomial: `0x11021`
- Init: `0x0000`
- XorOut: `0x0000`
- Reverse: `False`

---

#### `Frame`
Tworzenie i parsowanie ramek protokołu UART.

##### Format ramki:
```
[LEN][ADDR][CMD_H][CMD_L][DATA...][CRC_H][CRC_L]
```

- **LEN**: Długość `CMD + DATA` (2-64 bajty)
- **ADDR**: Adres urządzenia (1 bajt)
- **CMD**: Komenda (2 bajty: CMD_H, CMD_L)
- **DATA**: Opcjonalne dane (N bajtów)
- **CRC**: CRC16-XMODEM z `LEN + ADDR + CMD + DATA` (2 bajty, big-endian)

##### Metody statyczne:

**`create(target_id_data: bytes) -> bytearray`**

Tworzy kompletną ramkę.

```python
# Przykład: ADDR=0x01, CMD=0x1001, DATA=[0x01, 0x00]
frame_data = bytes([0x01, 0x10, 0x01, 0x01, 0x00])
frame = Frame.create(frame_data)
# Zwraca: [LEN][ADDR][CMD][DATA][CRC]
```

**`parse(frame: bytes, check_crc: bool = True) -> dict`**

Parsuje ramkę i zwraca słownik.

```python
parsed = Frame.parse(frame_bytes)
# Zwraca:
{
    'len': 4,                    # Długość CMD+DATA
    'addr': 0x01,                # Adres
    'cmd': b'\x10\x01',          # Komenda (bytes)
    'data': b'\x01\x00',         # Dane (bytes)
    'crc': b'\xAB\xCD'           # CRC (bytes)
}
```

**Wyjątki:**
- `ValueError` - Nieprawidłowa długość lub błąd CRC

---

#### `UARTHandler`
Obsługa komunikacji UART z idle-based detection.

**Konstruktor:**
```python
UARTHandler(serial_port: SerialPort)
```

**Parametry idle:**
- `idle_timeout = 0.017` (17ms) - Czas bezczynności rozdzielający transakcje

##### Metody:

**`send_data(target_id_data: bytes, timeout: float = 2) -> bool`**

Wysyła ramkę po upewnieniu się że linia jest bezczynna przez wymagany czas.

```python
# Przykład: Wysłanie START cyklu
cmd_data = bytes([0x01, 0x10, 0x01, 0x01, 0x00])
success = uart_handler.send_data(cmd_data)
```

**Zwraca:**
- `True` - Dane wysłane pomyślnie
- `False` - Timeout lub błąd

---

**`read_data(timeout: float = None) -> Generator[bytes, None, None]`**

Generator odbierający kompletne transakcje UART (rozdzielone idle gaps).

```python
for transaction in uart_handler.read_data(timeout=5.0):
    if transaction is None:
        print("Timeout - brak danych")
    else:
        print(f"Otrzymano: {transaction.hex().upper()}")
```

**Zasada działania:**
1. Zbiera bajty z portu
2. Wykrywa idle gap (17ms bezczynności)
3. Zwraca kompletną transakcję jako `bytes`
4. Po `timeout` sekundach bez ruchu zwraca `None`

---

**`decode_transaction(data: bytes) -> list`**

Dekoduje jedną transakcję UART na listę zdarzeń (ramki + ACK).

```python
events = uart_handler.decode_transaction(transaction)
for event in events:
    if isinstance(event, bytes):
        print(f"FRAME: {event.hex().upper()}")
    elif isinstance(event, AckType):
        print(f"ACK: {event.name}")
```

**Zwraca:**
- Lista zawierająca `bytes` (ramki) i `AckType` (ACK)

**Reguły dekodowania:**
1. Transakcja ZAWSZE zaczyna się od ramki (LEN byte)
2. ACK może wystąpić TYLKO po prawidłowej ramce
3. CRC jest obliczane z: `LEN + ADDR + CMD + DATA`
4. Błędny CRC → cała transakcja odrzucona
5. Brak sliding-window resync wewnątrz transakcji

---

## 🎯 core_app.py

### Opis
Główna logika aplikacji orkiestrująca odbiór danych, detekcję cykli, logowanie i monitoring stanu połączenia. Używa wielowątkowości do równoległego przetwarzania.

---

### Klasy

#### `CycleCounter`
Zarządza persystentnym licznikiem cykli (przetrwa restart).

**Konstruktor:**
```python
CycleCounter(counter_file: str = config.COUNTER_FILE)
```

**Metody:**

| Metoda | Opis |
|--------|------|
| `load() -> int` | Wczytuje licznik z pliku |
| `get_next() -> int` | Zwraca następny numer i **inkrementuje** licznik ⚠️ |
| `get_current() -> int` ⭐ | Zwraca bieżący numer **bez inkrementacji** (safe) |
| `_save()` | Zapisuje licznik do pliku (thread-safe) |

**Różnica `get_next()` vs `get_current()`:**

```python
counter = CycleCounter()

# ⚠️ UWAGA: get_next() ma side effect
num1 = counter.get_next()  # Zwraca 42, zapisuje 43 do pliku
num2 = counter.get_next()  # Zwraca 43, zapisuje 44 do pliku

# ✅ get_current() - read-only, bez side effects
num = counter.get_current()  # Zwraca 42 wielokrotnie
num = counter.get_current()  # Zwraca 42 wielokrotnie
```

**Zastosowanie `get_current()`:**
- Health check endpoint (`GET /health`) - nie inkrementuje licznika
- Monitoring dashboards
- Status queries bez wpływu na stan

---

#### `CycleEvent` (Enum)
Typy zdarzeń cyklu.

```python
CycleEvent.STARTED  # Cykl rozpoczęty
CycleEvent.ENDED    # Cykl zakończony
```

---

#### `CycleDetector`
Wykrywa początek i koniec cyklu na podstawie `CMD + DATA`.

**Konstruktor:**
```python
CycleDetector(
    cycle_cmd: bytes = config.CYCLE_CMD,
    start_data: bytes = config.CYCLE_START_DATA,
    end_data: bytes = config.CYCLE_END_DATA
)
```

**Metoda:**
```python
check_frame(frame_bytes: bytes) -> Optional[CycleEvent]
```

**Zwraca:**
- `CycleEvent.STARTED` - Wykryto START cyklu
- `CycleEvent.ENDED` - Wykryto END cyklu
- `None` - Brak zdarzenia cyklu

**Logika:**
- Porównuje `CMD` i `DATA` z ramki
- Śledzi stan (`is_active`)
- Loguje ostrzeżenia przy duplikatach START/END

---

#### `LogManager`
Zarządza plikami logów cykli (tworzenie, zapis, zamykanie).

**Konstruktor:**
```python
LogManager(logs_dir: str = config.LOGS_DIR)
```

**Metody:**

| Metoda | Opis |
|--------|------|
| `start_new_log(cycle_number, timestamp) -> str` | Tworzy nowy plik logu dla cyklu |
| `write_line(text: str)` | Zapisuje linię do aktualnego logu |
| `write_interruption_note(timestamp, reason)` | Loguje przerwanie połączenia |
| `write_resume_note(timestamp)` | Loguje wznowienie połączenia |
| `close_log()` | Zamyka aktualny plik logu |

**Format nazwy pliku:**
```
cycle_0042_2026-02-17_11-29-19.txt
```

**Struktura logu:**
```
=== CYCLE 0042 LOG ===
Started: 2026-02-17 11:29:19.123
============================================================
[logi ramek...]
============================================================
Log closed: 2026-02-17 11:35:42.987
============================================================
```

---

#### `AppLogger`
Zarządza logiem operacyjnym aplikacji (diagnostyka, błędy, eventy).

**Konstruktor:**
```python
AppLogger(app_log_dir: str = config.APP_LOG_DIR)
```

**Metody:**
- `log_startup()` - Loguje start aplikacji
- `log_shutdown()` - Loguje zamknięcie
- `log_error(message)` - Loguje błąd
- `log_warning(message)` - Loguje ostrzeżenie
- `log_info(message)` - Loguje informację

**Auto-cleanup:**
- Usuwa logi starsze niż `APP_LOG_RETENTION_DAYS`

**Format logu:**
```
2026-02-17 11:29:19.123 | INFO     | Application started
2026-02-17 11:29:20.456 | WARNING  | CRC error in frame: 04010A0B1234
2026-02-17 11:35:42.987 | INFO     | Application shutdown
```

---

### Funkcje pomocnicze formatowania

#### `format_frame_compact(frame_dict, direction, timestamp) -> str`
Formatuje ramkę w kompaktowy jednoliniowy format.

**Przykład:**
```
2026-02-17 11:29:19.123 | RX | LEN=04 ADDR=01 CMD=1001 DATA=0100 CRC=ABCD
```

---

#### `format_ack_compact(ack_type, timestamp) -> str`
Formatuje ACK w kompaktowy format.

**Przykład:**
```
2026-02-17 11:29:19.456 | RX | ACK_OK
```

---

#### `format_crc_error_compact(raw_frame, timestamp, direction, error) -> str`
Formatuje ramkę z błędem CRC.

**Przykład:**
```
2026-02-17 11:29:19.789 | RX | CRC_ERROR | RAW=04010A0B1234FFFF | Invalid CRC
```

---

#### `decode_frame_to_dict(raw_frame: bytes) -> Optional[dict]`
Dekoduje surową ramkę do słownika używając `Frame.parse`.

---

### `ApplicationService` - Główna klasa

Orkiestruje całą aplikację logowania UART.

**Konstruktor:**
```python
ApplicationService(uart_handler: UARTHandler)
```

**Zarządza:**
- ✅ Odbiorem danych z UART (wątek RX)
- ✅ Przetwarzaniem transakcji (wątek process)
- ✅ Wykrywaniem cykli
- ✅ Logowaniem do plików
- ✅ Monitorowaniem stanu połączenia
- ✅ Wykrywaniem przerw w komunikacji

---

#### Architektura wątkowa:

```
┌─────────────────┐
│   UART (HW)     │
└────────┬────────┘
         │
    ┌────▼────────┐
    │ RX Worker   │ ──► rx_queue (1000 elementów)
    │  (Thread)   │
    └─────────────┘
                        │
                   ┌────▼───────────┐
                   │ Process Worker │
                   │   (Thread)     │
                   └────┬───────────┘
                        │
          ┌─────────────┼─────────────┐
          │             │             │
    ┌─────▼──────┐ ┌───▼────┐ ┌──────▼──────┐
    │CycleDetector│ │ Logger │ │  AppLogger  │
    └────────────┘ └────────┘ └─────────────┘
```

---

#### Metody główne:

**`start()`**
Uruchamia serwis aplikacji (wątki RX i przetwarzania).

```python
app_service.start()
```

**Co się dzieje:**
1. Ustawia `_running = True`
2. Loguje startup do app log
3. Startuje wątek RX (`_rx_worker`)
4. Startuje wątek process (`_process_worker`)

---

**`stop()`**
Zatrzymuje serwis aplikacji (graceful shutdown).

```python
app_service.stop()
```

**Co się dzieje:**
1. Ustawia `_running = False`
2. Czeka na zakończenie wątków (max 5s każdy)
3. Zamyka aktywny log cyklu
4. Loguje shutdown do app log

---

**`get_status() -> dict`**
Zwraca aktualny status aplikacji (thread-safe, read-only).

```python
status = app_service.get_status()
print(status)
```

**Zwraca:**
```python
{
    'running': True,                              # Czy aplikacja działa
    'cycle_active': True,                         # Czy cykl aktywny
    'current_cycle': 42,                          # Numer aktualnego cyklu
    'current_log_filename': 'cycle_0042_...txt',  # Nazwa pliku logu
    'last_activity_time': 1708167559.123,         # Unix timestamp
    'rx_queue_size': 5                            # Rozmiar kolejki RX
}
```

---

**`is_running() -> bool`** ⭐ *Nowość*

Sprawdza czy aplikacja działa (thread-safe getter).

```python
if app_service.is_running():
    print("ApplicationService aktywny")
```

**Zastosowanie:**
- Health check endpoint (`GET /health`)
- Walidacja przed operacjami (start/stop)
- Status monitoring w GUI

---

**`is_in_cycle() -> bool`** ⭐ *Nowość*

Sprawdza czy aktywny cykl jest w toku (thread-safe getter).

```python
if app_service.is_in_cycle():
    print(f"Cykl {app_service.get_status()['current_cycle']} w trakcie")
else:
    print("Brak aktywnego cyklu")
```

**Zastosowanie:**
- Health check endpoint (`GET /health`)
- Dashboard GUI - wyświetlanie stanu cyklu
- Metryki monitoringu

---

#### Metody wewnętrzne (workers):

**`_rx_worker()`**
Wątek odbierający dane z UART i przekazujący do kolejki.

**Działanie:**
1. Nasłuchuje transakcji z `uart_handler.read_data()`
2. Przekazuje do `rx_queue`
3. Aktualizuje `last_activity_time`
4. Obsługuje `queue.Full` (loguje i dropuje)

---

**`_process_worker()`**
Wątek przetwarzający transakcje z kolejki.

**Działanie:**
1. Pobiera transakcje z `rx_queue` (timeout 1s)
2. Wykrywa timeout połączenia (brak danych przez `INTERRUPTION_TIMEOUT`)
3. Loguje przerwania i wznowienia
4. Przetwarza transakcje (`_process_transaction`)

---

**`_process_transaction(transaction: bytes)`**
Przetwarza pojedynczą transakcję UART.

**Kroki:**
1. Dekoduje transakcję na zdarzenia (ramki + ACK)
2. Dla każdego zdarzenia wywołuje:
   - `_process_frame()` dla ramek
   - `_process_ack()` dla ACK

---

**`_process_frame(frame_bytes: bytes, timestamp: datetime)`**
Przetwarza pojedynczą ramkę.

**Kroki:**
1. Sprawdza czy to komenda cyklu (`cycle_detector.check_frame`)
2. Obsługuje START/END cyklu
3. Dekoduje ramkę do słownika
4. Sprawdza CRC
5. Formatuje linię logu
6. Zapisuje do pliku jeśli cykl aktywny

---

**`_process_ack(ack_type: AckType, timestamp: datetime)`**
Przetwarza ACK.

**Kroki:**
1. Formatuje ACK do logu
2. Zapisuje do pliku jeśli cykl aktywny

---

**`_handle_cycle_start(timestamp: datetime)`**
Obsługuje start nowego cyklu.

**Kroki:**
1. Sprawdza czy cykl nie jest już aktywny
2. Pobiera nowy numer cyklu (`cycle_counter.get_next()`)
3. Ustawia `cycle_active = True`
4. Tworzy nowy plik logu
5. Loguje do app log

---

**`_handle_cycle_end(timestamp: datetime)`**
Obsługuje koniec cyklu.

**Kroki:**
1. Sprawdza czy cykl jest aktywny
2. Zamyka plik logu
3. Loguje do app log
4. Ustawia `cycle_active = False`

---

## 🚀 Przykład użycia

### Podstawowa konfiguracja

```python
from my_project.core import config
from my_project.core.uart import SerialPort, UARTHandler
from my_project.core.core_app import ApplicationService
import serial

# 1. Utworzenie i otwarcie portu szeregowego
port = SerialPort(
    port=config.DEFAULT_PORT,
    baudrate=config.DEFAULT_BAUDRATE,
    parity=config.get_parity_constant(config.DEFAULT_PARITY),
    stopbits=config.DEFAULT_STOPBITS,
    timeout=config.DEFAULT_TIMEOUT
)
port.open_port()

# 2. Utworzenie UART Handler
uart_handler = UARTHandler(port)

# 3. Utworzenie Application Service
app_service = ApplicationService(uart_handler)

# 4. Uruchomienie aplikacji
app_service.start()

# 5. Wysłanie START cyklu
start_cmd = bytes([0x01, 0x10, 0x01, 0x01, 0x00])  # ADDR + CMD + DATA
uart_handler.send_data(start_cmd)

# 6. Sprawdzenie statusu
status = app_service.get_status()
print(f"Cycle active: {status['cycle_active']}")
print(f"Current cycle: {status['current_cycle']}")
print(f"Log file: {status['current_log_filename']}")

# 7. Wysłanie STOP cyklu
stop_cmd = bytes([0x01, 0x10, 0x01, 0x03, 0x00])  # ADDR + CMD + DATA
uart_handler.send_data(stop_cmd)

# 8. Zatrzymanie aplikacji
app_service.stop()

# 9. Zamknięcie portu
port.close()
```

---

## 🔍 Debugowanie

### Poziomy logowania (Python logging)

```python
import logging

# DEBUG - Szczegółowe informacje diagnostyczne
logging.getLogger('my_project.core.uart').setLevel(logging.DEBUG)

# INFO - Normalne działanie (domyślne)
logging.getLogger('my_project.core.core_app').setLevel(logging.INFO)

# WARNING - Ostrzeżenia (np. duplikat START cyklu)
# ERROR - Błędy (np. CRC fail)
# CRITICAL - Krytyczne błędy
```

### Logowanie w module

- **uart.py** - Loguje TX/RX ramek, CRC, ACK
- **core_app.py** - Loguje cykle, przerwania, błędy

### Pliki logów

1. **Logi cykli** → `logs/cycle_XXXX_YYYY-MM-DD_HH-MM-SS.txt`
   - Zawiera surowe ramki z timestampami
   - Jeden plik per cykl

2. **Logi aplikacyjne** → `app_logs/app_YYYY-MM-DD.log`
   - Diagnostyka, błędy, eventy
   - Jeden plik dziennie
   - Auto-cleanup po `APP_LOG_RETENTION_DAYS`

---

## ⚙️ Dostosowywanie

### Zmiana parametrów detekcji cykli

W [config.py](config.py):

```python
# Własny protokół cykli
CYCLE_CMD = bytes([0x20, 0x05])           # CMD = 2005
CYCLE_START_DATA = bytes([0xAA])          # START = AA
CYCLE_END_DATA = bytes([0xBB])            # END = BB
```

### Zmiana timeoutu przerwania

```python
INTERRUPTION_TIMEOUT = 10.0  # 10 sekund zamiast 5
```

### Zmiana portu UART

```python
DEFAULT_PORT = 'COM3'  # Windows
# lub
DEFAULT_PORT = '/dev/ttyAMA0'  # Raspberry Pi hardware UART
```

### Zmiana baudrate

```python
DEFAULT_BAUDRATE = 115200  # Szybsza komunikacja
```

---

## 📊 Monitoring wydajności

### Metryki do śledzenia:

```python
status = app_service.get_status()

# Rozmiar kolejki RX (powinien być blisko 0)
queue_size = status['rx_queue_size']
if queue_size > 100:
    print("WARNING: RX queue is filling up!")

# Czas ostatniej aktywności
import time
elapsed = time.time() - status['last_activity_time']
print(f"Last activity: {elapsed:.2f}s ago")
```

---

## 🛡️ Thread Safety

### Bezpieczne wielowątkowo:

✅ `CycleCounter` - używa `threading.Lock`  
✅ `LogManager` - używa `threading.Lock`  
✅ `ApplicationService.get_status()` - używa `_status_lock`  
✅ `queue.Queue` - thread-safe z natury  

### Niebezpieczne (tylko z jednego wątku):

⚠️ `uart_handler.send_data()` - wywołuj tylko z głównego wątku  
⚠️ Bezpośredni dostęp do `serial_port` - używaj przez `UARTHandler`

---

## 📝 Licencja i autorzy

Moduł napisany dla projektu UART Logger - Dbus_Logger.

**Data utworzenia:** 2026-02  
**Język:** Python 3.8+  
**Zależności:** `pyserial`, `crcmod`

---

## 🔗 Zobacz też

- [API.md](../../API.md) - Dokumentacja REST API
- [README.md](../../README.md) - Główny README projektu
- [demo_hardware_uart.py](../../demo_hardware_uart.py) - Przykład użycia z prawdziwym UART
