# API Module - Dbus Logger

## 📋 Przegląd

Moduł `api` dostarcza REST API dla aplikacji Dbus Logger, wykorzystując framework FastAPI. Łączy funkcjonalności z modułu [core](../core/) z interfejsem HTTP, umożliwiając zdalne monitorowanie i kontrolę logowania komunikacji Dbus.

**Architektura:** Backend działa jako **samodzielny proces** (niezależnie od GUI), idealny do uruchomienia na Raspberry Pi w sieci LAN.

## 📦 Struktura modułu

```
api/
├── main.py          # Główny plik aplikacji FastAPI
├── README.md        # Ten plik
└── __init__.py      # Inicjalizacja modułu
```

---

## 🚀 Uruchomienie

### Zalecany sposób (Production - Multi-Station)

**Backend na Raspberry Pi (stanowisko):**
```bash
python start_backend.py
```

**Co się uruchamia:**
- Serwer FastAPI na `http://0.0.0.0:8000` (dostępny w sieci LAN)
- Połączenie z prawdziwym portem UART (z konfiguracji)
- Automatyczna inicjalizacja ApplicationService
- Wątki RX i przetwarzania danych
- Opcjonalna rejestracja mDNS dla auto-discovery

**Frontend na PC operatora:**
```bash
python start_frontend.py
```
Zobacz: [GUI Module](../gui/)

### Alternatywny sposób (uvicorn bezpośrednio)

```bash
uvicorn my_project.api.main:app --host 0.0.0.0 --port 8000
```

### Zmienne środowiskowe

```bash
# Ustaw ID stanowiska (opcjonalne, domyślnie hostname)
export STATION_ID="RPI-01"

python start_backend.py
```

### Dostępne interfejsy po starcie

| URL | Opis |
|-----|------|
| http://localhost:8000 | Główna strona HTML z linkami |
| http://localhost:8000/docs | Interaktywna dokumentacja Swagger UI |
| http://localhost:8000/redoc | Dokumentacja ReDoc |
| http://localhost:8000/api | Informacje o API (JSON) |
| http://localhost:8000/health | **Health check stanowiska** (station_id, UART, uptime) |
| http://localhost:8000/status | Status aplikacji (JSON) |

---

## 📡 main.py - Szczegółowa dokumentacja

### Architektura Multi-Station

```
┌─────────────────────────────────────────────────────┐
│          Sieć LAN (192.168.x.x)                     │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Raspberry Pi #1 (192.168.1.10)                    │
│  ┌──────────────────────────────────┐              │
│  │   FastAPI Backend (port 8000)    │              │
│  │   + ApplicationService + UART    │              │
│  └──────────────────────────────────┘              │
│                                                     │
│  Raspberry Pi #2 (192.168.1.11)                    │
│  ┌──────────────────────────────────┐              │
│  │   FastAPI Backend (port 8000)    │              │
│  │   + ApplicationService + UART    │              │
│  └──────────────────────────────────┘              │
│                                                     │
│  PC Operatora                                       │
│  ┌──────────────────────────────────┐              │
│  │   NiceGUI Frontend (port 8080)   │              │
│  │   Monitoruje wszystkie stanowiska│              │
│  └──────────────────────────────────┘              │
└─────────────────────────────────────────────────────┘
```

---

## 🔧 Komponenty główne

### 1️⃣ Modele Pydantic

#### `SendFrameRequest`
Model dla żądania wysłania ramki UART przez API.

```python
class SendFrameRequest(BaseModel):
    addr: int       # Adres urządzenia (0-255)
    cmd_h: int      # Komenda HIGH byte (0-255)
    cmd_l: int      # Komenda LOW byte (0-255)
    data: List[int] # Opcjonalne dane (lista bajtów 0-255)
```

**Przykład JSON:**
```json
{
  "addr": 21,
  "cmd_h": 16,
  "cmd_l": 1,
  "data": [1, 0]
}
```

**Walidacja automatyczna:**
- ✅ Wszystkie wartości muszą być w zakresie 0-255
- ✅ `addr`, `cmd_h`, `cmd_l` są wymagane
- ✅ `data` jest opcjonalne (domyślnie pusta lista)

---

### 2️⃣ Inicjalizacja UART

#### `initialize_uart_and_service() -> tuple`

Funkcja inicjalizująca wszystkie komponenty UART i ApplicationService.

**Kroki inicjalizacji:**

1. **Utworzenie SerialPort**
   ```python
   port = SerialPort(
       port=config.DEFAULT_PORT,      # np. COM5 / /dev/ttyAMA0
       baudrate=config.DEFAULT_BAUDRATE,
       parity=config.get_parity_constant(config.DEFAULT_PARITY),
       stopbits=config.DEFAULT_STOPBITS,
       timeout=config.DEFAULT_TIMEOUT
   )
   ```

2. **Otwarcie portu**
   ```python
   port.open_port()  # Może rzucić serial.SerialException
   ```

3. **Utworzenie UARTHandler**
   ```python
   handler = UARTHandler(port)
   ```

4. **Utworzenie ApplicationService**
   ```python
   service = ApplicationService(handler)
   ```

5. **Uruchomienie wątków**
   ```python
   service.start()  # Uruchamia RX worker i Process worker
   ```

**Zwraca:**
```python
(serial_port, uart_handler, app_service)  # tuple
```

**Wyjątki:**
- `RuntimeError` - Jeśli nie można otworzyć portu UART
- Loguje szczegółowe informacje diagnostyczne

**Komunikaty błędów:**

Jeśli port nie może zostać otwarty, funkcja loguje:
```
✗ BŁĄD: Nie można otworzyć portu szeregowego!
Port: COM5
Przyczyna: [SerialException details]

Możliwe rozwiązania:
  1. Sprawdź czy urządzenie jest podłączone
  2. Sprawdź czy port nie jest używany przez inną aplikację
  3. Zmień DEFAULT_PORT w config.py
  4. Dostępne porty: ['COM3', 'COM5']
```

---

### 3️⃣ Zarządzanie cyklem życia (Lifespan)

#### `lifespan(app: FastAPI)` - Context Manager

FastAPI lifespan zarządza startem i zamknięciem aplikacji.

**STARTUP (przed przyjęciem requestów):**

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    global serial_port, uart_handler, app_service
    
    # 1. Inicjalizacja
    serial_port, uart_handler, app_service = initialize_uart_and_service()
    
    # 2. Aplikacja gotowa
    logger.info("FastAPI ready - API endpoints available")
    
    yield  # <-- Aplikacja działa, obsługuje requesty
    
    # SHUTDOWN (po otrzymaniu SIGTERM/SIGINT)
    ...
```

**SHUTDOWN (po zakończeniu):**

```python
    # SHUTDOWN
    if app_service:
        app_service.stop()  # Zatrzymuje wątki RX i process
    
    if serial_port:
        serial_port.close()  # Zamyka port szeregowy
```

**Kolejność zamykania:**
1. ApplicationService (zatrzymanie wątków)
2. SerialPort (zamknięcie połączenia)
3. Logi potwierdzające shutdown

---

### 4️⃣ Aplikacja FastAPI

#### Konfiguracja

```python
app = FastAPI(
    title="Dbus Logger API",
    description="REST API dla aplikacji do logowania komunikacji UART z detekcją cykli",
    version="1.0.0",
    lifespan=lifespan
)
```

#### CORS Middleware

Umożliwia dostęp z zewnętrznych aplikacji (np. GUI na innym porcie).

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # W produkcji: konkretne domeny
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

⚠️ **Uwaga produkcyjna:** Zamień `allow_origins=["*"]` na konkretne domeny.

---

## 🌐 Endpointy API

### 📄 `GET /` - Strona główna HTML

Zwraca elegancką stronę HTML z linkami do dokumentacji i endpointów.

**Odpowiedź:** HTML (response_class=HTMLResponse)

**Zawartość:**
- Status aplikacji
- Linki do dokumentacji (/docs, /redoc)
- Lista dostępnych endpointów
- Informacja o GUI (NiceGUI)

---

### 📋 `GET /api` - Informacje o API

Zwraca JSON z metadanymi API.

**Odpowiedź:**
```json
{
  "name": "Dbus Logger API",
  "version": "1.0.0",
  "status": "running",
  "description": "REST API dla monitoringu i kontroli aplikacji Dbus Logger",
  "gui": {
    "type": "NiceGUI",
    "note": "Run separately: python start_frontend.py (port 8080)"
  },
  "endpoints": {
    "health": "GET /health - Health check stanowiska",
    "status": "GET /status - Status aplikacji",
    "logs": "GET /logs - Lista plików logów",
    "log_content": "GET /logs/{filename} - Zawartość logu",
    "log_download": "GET /logs/{filename}/download - Pobierz log",
    "send_frame": "POST /uart/send - Wysłanie ramki UART",
    "docs": "GET /docs - Interaktywna dokumentacja API"
  }
}
```

---

### 💚 `GET /health` - Health check stanowiska

**Nowy endpoint dla multi-station monitoring.** Zwraca rozszerzone informacje diagnostyczne o stanowisku.

**Odpowiedź:**
```json
{
  "status": "healthy",
  "station_id": "RPI-01",
  "hostname": "raspberry-pi-lab-01",
  "ip_address": "192.168.1.10",
  "uart": {
    "port": "/dev/ttyAMA0",
    "connected": true,
    "baudrate": 9600
  },
  "service": {
    "running": true,
    "uptime_seconds": 3600.5,
    "cycles_total": 42,
    "in_cycle": true
  },
  "timestamp": "2026-02-19T12:15:30.123456"
}
```

**Pola:**

| Pole | Typ | Opis |
|------|-----|------|
| `status` | str | Status ogólny: "healthy" lub "unhealthy" |
| `station_id` | str | ID stanowiska (env `STATION_ID` lub hostname) |
| `hostname` | str | Nazwa hosta systemu |
| `ip_address` | str | Lokalny adres IP w sieci |
| `uart.port` | str | Nazwa portu UART |
| `uart.connected` | bool | Czy port jest otwarty |
| `uart.baudrate` | int | Prędkość transmisji |
| `service.running` | bool | Czy ApplicationService działa |
| `service.uptime_seconds` | float | Czas działania w sekundach |
| `service.cycles_total` | int | Liczba zakończonych cykli |
| `service.in_cycle` | bool | Czy trwa aktywny cykl |
| `timestamp` | str | ISO timestamp odpowiedzi |

**Status "unhealthy" gdy:**
- UART nie jest połączony (`uart.connected = false`)
- ApplicationService nie działa (`service.running = false`)

**Przykład użycia:**
```bash
# Health check
curl http://192.168.1.10:8000/health

# Monitoring wszystkich stanowisk
for ip in 192.168.1.{10..12}; do
  echo "Checking $ip..."
  curl -s http://$ip:8000/health | jq '.status, .station_id'
done
```

**Use case:**
- Frontend NiceGUI do wyświetlania statusu wszystkich stanowisk
- Monitoring tools (Prometheus, Nagios)
- Auto-discovery w sieci lokalnej
- Dashboard z metrykami wielu stanowisk

---

### 📊 `GET /status` - Status aplikacji

Zwraca aktualny status aplikacji Dbus Logger.

**Odpowiedź:**
```json
{
  "running": true,
  "cycle_active": true,
  "current_cycle": 42,
  "current_log_filename": "cycle_0042_2026-02-17_11-29-19.txt",
  "last_activity_time": 1708167559.123,
  "last_activity_readable": "2026-02-17 11:29:19",
  "rx_queue_size": 3
}
```

**Pola:**

| Pole | Typ | Opis |
|------|-----|------|
| `running` | bool | Czy ApplicationService działa |
| `cycle_active` | bool | Czy cykl jest aktywny |
| `current_cycle` | int/null | Numer aktualnego cyklu |
| `current_log_filename` | str/null | Nazwa pliku logu |
| `last_activity_time` | float | Unix timestamp ostatniej aktywności |
| `last_activity_readable` | str | Czytelny timestamp |
| `rx_queue_size` | int | Ilość elementów w kolejce RX |

**Błędy:**
- `503 Service Unavailable` - Jeśli ApplicationService nie jest zainicjalizowany

**Przykład użycia:**
```bash
curl http://localhost:8000/status
```

---

### 📁 `GET /logs` - Lista logów

Zwraca listę wszystkich plików logów cykli.

**Odpowiedź:**
```json
{
  "logs": [
    {
      "filename": "cycle_0042_2026-02-17_11-29-19.txt",
      "cycle_number": 42,
      "size_bytes": 15234,
      "modified": "2026-02-17 11:35:42",
      "path": "logs/cycle_0042_2026-02-17_11-29-19.txt"
    },
    {
      "filename": "cycle_0041_2026-02-17_10-15-30.txt",
      "cycle_number": 41,
      "size_bytes": 8921,
      "modified": "2026-02-17 10:25:15",
      "path": "logs/cycle_0041_2026-02-17_10-15-30.txt"
    }
  ],
  "count": 2,
  "directory": "logs/"
}
```

**Sortowanie:** Od najnowszych (największy numer cyklu)

**Pola logu:**

| Pole | Typ | Opis |
|------|-----|------|
| `filename` | str | Nazwa pliku |
| `cycle_number` | int/null | Numer cyklu (z nazwy pliku) |
| `size_bytes` | int | Rozmiar pliku w bajtach |
| `modified` | str | Data ostatniej modyfikacji |
| `path` | str | Pełna ścieżka do pliku |

**Przykład użycia:**
```bash
curl http://localhost:8000/logs | jq
```

---

### 📄 `GET /logs/{filename}` - Zawartość logu

Zwraca zawartość konkretnego pliku logu jako JSON.

**Parametry:**
- `filename` (path param) - Nazwa pliku (np. `cycle_0042_2026-02-17_11-29-19.txt`)

**Odpowiedź:**
```json
{
  "filename": "cycle_0042_2026-02-17_11-29-19.txt",
  "cycle_number": 42,
  "lines": [
    "=== CYCLE 0042 LOG ===",
    "Started: 2026-02-17 11:29:19.123",
    "2026-02-17 11:29:19.123 | ADDR:21 CMD:1001 DATA:01 00 ACK:OK | Cykl START",
    "2026-02-17 11:29:20.456 | ADDR:21 CMD:2005 DATA:FF | ACK:OK",
    "..."
  ],
  "frames_count": 156,
  "size_bytes": 15234
}
```

**Pola:**

| Pole | Typ | Opis |
|------|-----|------|
| `filename` | str | Nazwa pliku logu |
| `cycle_number` | int | Numer cyklu (sparsowany z nazwy) |
| `lines` | array[str] | Linie pliku (każda jako osobny string) |
| `frames_count` | int | Liczba ramek UART (linie z timestampem) |
| `size_bytes` | int | Rozmiar pliku w bajtach |

**Bezpieczeństwo:**

✅ **Walidacja nazwy pliku:**
```python
if not re.match(r'^cycle_.*\.txt$', filename):
    raise HTTPException(400, "Invalid filename format")
```

✅ **Ochrona przed Path Traversal:**
```python
if '..' in filename or '/' in filename or '\\' in filename:
    raise HTTPException(400, "Path traversal detected")
```

**Błędy:**
- `400 Bad Request` - Nieprawidłowy format nazwy lub path traversal
- `404 Not Found` - Plik nie istnieje
- `500 Internal Server Error` - Błąd odczytu pliku

**Przykład użycia:**
```bash
curl http://localhost:8000/logs/cycle_0042_2026-02-17_11-29-19.txt
```

---

### 💾 `GET /logs/{filename}/download` - Pobierz log

Pobiera log jako plik (do pobrania przez przeglądarkę).

**Parametry:**
- `filename` (path param) - Nazwa pliku

**Odpowiedź:**
- Plik tekstowy do pobrania
- Header: `Content-Disposition: attachment; filename=...`
- Media type: `text/plain`

**Bezpieczeństwo:**
- Identyczna walidacja jak w `/logs/{filename}`
- Ochrona przed path traversal

**Przykład użycia (przeglądarka):**
```
http://localhost:8000/logs/cycle_0042_2026-02-17_11-29-19.txt/download
```

**Przykład użycia (curl):**
```bash
curl -O http://localhost:8000/logs/cycle_0042_2026-02-17_11-29-19.txt/download
```

---

### ⚡ `POST /uart/send` - Wyślij ramkę UART

Wysyła ramkę UART przez port szeregowy.

**Request Body:**
```json
{
  "addr": 21,
  "cmd_h": 16,
  "cmd_l": 1,
  "data": [1, 0]
}
```

**Odpowiedź (sukces):**
```json
{
  "success": true,
  "message": "Frame sent successfully",
  "payload_hex": "1510010100",
  "addr": 21,
  "cmd": "1001",
  "data_hex": "0100"
}
```

**Przykłady użycia:**

#### START cyklu (CMD=1001, DATA=01 00)
```bash
curl -X POST http://localhost:8000/uart/send \
  -H "Content-Type: application/json" \
  -d '{
    "addr": 21,
    "cmd_h": 16,
    "cmd_l": 1,
    "data": [1, 0]
  }'
```

#### STOP cyklu (CMD=1001, DATA=03 00)
```bash
curl -X POST http://localhost:8000/uart/send \
  -H "Content-Type: application/json" \
  -d '{
    "addr": 21,
    "cmd_h": 16,
    "cmd_l": 1,
    "data": [3, 0]
  }'
```

#### Ramka bez danych (tylko CMD)
```bash
curl -X POST http://localhost:8000/uart/send \
  -H "Content-Type: application/json" \
  -d '{
    "addr": 1,
    "cmd_h": 10,
    "cmd_l": 11,
    "data": []
  }'
```

**Proces wysyłania:**

1. Walidacja danych wejściowych (Pydantic)
2. Budowanie payloadu: `ADDR + CMD_H + CMD_L + DATA`
3. Wywołanie `uart_handler.send_data(payload)`
4. Automatyczne dodanie LEN i CRC (przez `Frame.create()`)
5. Wysłanie po wykryciu idle line
6. Zwrócenie potwierdzenia

**Błędy:**

| Kod | Przyczyna |
|-----|-----------|
| `400 Bad Request` | Nieprawidłowa wartość bajtu (spoza 0-255) |
| `500 Internal Server Error` | Timeout przy wysyłaniu (linia nigdy nie była idle) |
| `503 Service Unavailable` | UART handler nie zainicjalizowany |

---

## 🔐 Bezpieczeństwo

### Walidacja danych wejściowych

✅ **Pydantic models** - Automatyczna walidacja typów i zakresów  
✅ **Regex dla nazw plików** - `^cycle_.*\.txt$`  
✅ **Path traversal protection** - Blokada `..`, `/`, `\`  
✅ **Zakres bajtów** - 0-255 dla wszystkich wartości UART  

### CORS

⚠️ Obecnie ustawione `allow_origins=["*"]` dla developerskiego środowiska.

**Produkcja - zalecana konfiguracja:**
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",  # NiceGUI
        "https://yourdomain.com"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
```

---

## 📊 Logging

### Format logów

```python
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

### Poziomy logowania w API

| Poziom | Przykład użycia |
|--------|-----------------|
| `INFO` | Wysłanie ramki, inicjalizacja, shutdown |
| `ERROR` | Błąd odczytu pliku, błąd wysyłania ramki |
| `CRITICAL` | Błąd inicjalizacji UART (crash startup) |

### Przykłady logów

**Startup:**
```
2026-02-17 11:29:15.123 - __main__ - INFO - ==============================
2026-02-17 11:29:15.124 - __main__ - INFO - INICJALIZACJA DBUS LOGGER
2026-02-17 11:29:15.125 - __main__ - INFO - System: WINDOWS
2026-02-17 11:29:15.126 - __main__ - INFO - Port: COM5
2026-02-17 11:29:15.127 - my_project.core.uart - INFO - Serial port COM5 initialized
2026-02-17 11:29:15.234 - my_project.core.uart - INFO - Port COM5 opened successfully.
2026-02-17 11:29:15.235 - __main__ - INFO - ✓ Port COM5 otwarty pomyślnie
2026-02-17 11:29:15.236 - __main__ - INFO - ✓ UART Handler utworzony
2026-02-17 11:29:15.237 - __main__ - INFO - ✓ Application Service utworzony
2026-02-17 11:29:15.345 - __main__ - INFO - ✓ Application Service uruchomiony
2026-02-17 11:29:15.346 - __main__ - INFO - ✓ INICJALIZACJA ZAKOŃCZONA POMYŚLNIE
```

**Wysłanie ramki:**
```
2026-02-17 11:30:42.567 - __main__ - INFO - Sending UART frame: payload=1510010100
2026-02-17 11:30:42.584 - my_project.core.uart - INFO - TX after idle gap: 041510010100ABCD
```

**Shutdown:**
```
2026-02-17 11:45:30.123 - __main__ - INFO - ==============================
2026-02-17 11:45:30.124 - __main__ - INFO - SHUTDOWN - Zamykanie aplikacji...
2026-02-17 11:45:30.125 - __main__ - INFO - Zatrzymywanie Application Service...
2026-02-17 11:45:35.234 - __main__ - INFO - ✓ Application Service zatrzymany
2026-02-17 11:45:35.235 - __main__ - INFO - Zamykanie portu szeregowego...
2026-02-17 11:45:35.345 - __main__ - INFO - ✓ Port szeregowy zamknięty
2026-02-17 11:45:35.346 - __main__ - INFO - ✓ SHUTDOWN ZAKOŃCZONY
```

---

## 🧪 Testowanie API

### 1️⃣ Curl

**Sprawdź status:**
```bash
curl http://localhost:8000/status | jq
```

**Lista logów:**
```bash
curl http://localhost:8000/logs | jq '.logs[] | {filename, cycle_number, size_bytes}'
```

**START cyklu:**
```bash
curl -X POST http://localhost:8000/uart/send \
  -H "Content-Type: application/json" \
  -d '{"addr": 21, "cmd_h": 16, "cmd_l": 1, "data": [1, 0]}'
```

### 2️⃣ Python (requests)

```python
import requests

BASE_URL = "http://localhost:8000"

# Status
status = requests.get(f"{BASE_URL}/status").json()
print(f"Cycle active: {status['cycle_active']}")

# Wyślij ramkę
response = requests.post(
    f"{BASE_URL}/uart/send",
    json={
        "addr": 21,
        "cmd_h": 16,
        "cmd_l": 1,
        "data": [1, 0]
    }
)
print(response.json())

# Lista logów
logs = requests.get(f"{BASE_URL}/logs").json()
for log in logs['logs'][:5]:
    print(f"Cycle {log['cycle_number']}: {log['filename']}")
```

### 3️⃣ Swagger UI (interaktywne)

Otwórz w przeglądarce:
```
http://localhost:8000/docs
```

- Testuj wszystkie endpointy w przeglądarce
- Automatyczna walidacja
- Przykłady requestów/responses
- "Try it out" dla każdego endpointa

---

## 🔄 Integracja z Core

API wykorzystuje moduł [core](../core/):

```python
from my_project.core import config
from my_project.core.uart import SerialPort, UARTHandler
from my_project.core.core_app import ApplicationService
```

**Przepływ danych:**

```
HTTP Request (POST /uart/send)
    │
    ▼
FastAPI endpoint
    │
    ▼
uart_handler.send_data(payload)
    │
    ▼
Frame.create(payload)  [dodaje LEN i CRC]
    │
    ▼
serial_port.write(frame)
    │
    ▼
UART Hardware
```

**Odbiór danych:**

```
UART Hardware
    │
    ▼
RX Worker Thread (z core)
    │
    ▼
rx_queue
    │
    ▼
Process Worker Thread
    │
    ▼
CycleDetector + LogManager
    │
    ▼
Pliki logów (logs/)
    │
    ▼
API GET /logs (udostępnia)
```

---

## 🚨 Obsługa błędów

### HTTPException

Wszystkie błędy zwracane jako standardowe HTTP status codes:

| Status | Znaczenie | Przykład |
|--------|-----------|----------|
| 400 | Bad Request | Nieprawidłowy format pliku, błędne dane |
| 404 | Not Found | Plik logu nie istnieje |
| 500 | Internal Server Error | Błąd odczytu pliku, błąd wysyłania |
| 503 | Service Unavailable | UART handler nie zainicjalizowany |

### Przykładowe odpowiedzi błędów

**404 Not Found:**
```json
{
  "detail": "Log file not found: cycle_9999_2026-02-17_11-29-19.txt"
}
```

**400 Bad Request:**
```json
{
  "detail": "Invalid filename format. Expected: cycle_*.txt, got: ../secret.txt"
}
```

**503 Service Unavailable:**
```json
{
  "detail": "UART handler not initialized"
}
```

---

## ⚙️ Konfiguracja

API korzysta z ustawień z [core/config.py](../core/config.py):

```python
# Port UART
config.DEFAULT_PORT          # COM5 / /dev/ttyAMA0
config.DEFAULT_BAUDRATE      # 9600

# Katalogi
config.LOGS_DIR              # "logs/" (dla endpointu /logs)
config.APP_LOG_DIR           # "app_logs/"

# Timeouty
config.DEFAULT_TIMEOUT       # 1.0s
config.INTERRUPTION_TIMEOUT  # 5.0s
```

### Zmiana portu API

```python
# W main.py na końcu:
uvicorn.run(
    "my_project.api.main:app",
    host="0.0.0.0",
    port=8080,  # <-- zmień port
    reload=False
)
```

---

## 📈 Monitoring i diagnostyka

### Status aplikacji

```bash
# Co 5 sekund sprawdzaj status
watch -n 5 'curl -s http://localhost:8000/status | jq'
```

### Rozmiar kolejki RX

```bash
curl -s http://localhost:8000/status | jq '.rx_queue_size'
```

**Interpretacja:**
- `0-10` - Normalne
- `10-100` - Możliwe spowolnienie przetwarzania
- `>100` - ⚠️ Kolejka się zapełnia (ryzyko drop)

### Ostatnia aktywność

```bash
curl -s http://localhost:8000/status | jq '.last_activity_readable'
```

---

## 🎯 Przykłady użycia

### Pełny cykl testowy

```bash
# 1. Sprawdź status początkowy
curl http://localhost:8000/status | jq '.cycle_active'
# Output: false

# 2. Wyślij START cyklu
curl -X POST http://localhost:8000/uart/send \
  -H "Content-Type: application/json" \
  -d '{"addr": 21, "cmd_h": 16, "cmd_l": 1, "data": [1, 0]}'

# 3. Sprawdź czy cykl się rozpoczął
curl http://localhost:8000/status | jq '.cycle_active'
# Output: true

# 4. Sprawdź numer cyklu i nazwę logu
curl http://localhost:8000/status | jq '{cycle: .current_cycle, log: .current_log_filename}'

# 5. Wyślij STOP cyklu
curl -X POST http://localhost:8000/uart/send \
  -H "Content-Type: application/json" \
  -d '{"addr": 21, "cmd_h": 16, "cmd_l": 1, "data": [3, 0]}'

# 6. Sprawdź czy cykl się zakończył
curl http://localhost:8000/status | jq '.cycle_active'
# Output: false

# 7. Znajdź ostatni log
curl http://localhost:8000/logs | jq '.logs[0].filename'

# 8. Pobierz zawartość logu
curl http://localhost:8000/logs/cycle_0042_2026-02-17_11-29-19.txt | jq '.content'

# 9. Pobierz plik
curl -O http://localhost:8000/logs/cycle_0042_2026-02-17_11-29-19.txt/download
```

---

## 🔗 Integracja z GUI

### NiceGUI (osobny proces)

API dostarcza backend dla GUI uruchamianego osobno:

```bash
# Terminal 1: API
python -m my_project.api.main

# Terminal 2: GUI
python demo_ngui.py  # lub gui_nicegui.py
```

GUI komunikuje się z API przez HTTP:
- `GET /status` - Odświeżanie statusu
- `GET /logs` - Lista logów
- `POST /uart/send` - Wysyłanie komend

---

## 📝 Najlepsze praktyki

### 1️⃣ Graceful Shutdown

```bash
# Zatrzymaj przez CTRL+C
# Aplikacja automatycznie:
# - Zatrzyma wątki RX i process
# - Zamknie aktywny log
# - Zamknie port UART
```

### 2️⃣ Monitoring kolejki RX

```python
status = requests.get("http://localhost:8000/status").json()
if status['rx_queue_size'] > 100:
    print("WARNING: Queue filling up!")
```

### 3️⃣ Timeout przy wysyłaniu

```python
# Timeout jest ustawiony na 2s w endpoint
# Jeśli linia UART nigdy nie jest idle, zwróci 500
response = requests.post(
    "http://localhost:8000/uart/send",
    json={"addr": 1, "cmd_h": 10, "cmd_l": 11, "data": []},
    timeout=5  # HTTP timeout (większy niż UART timeout)
)
```

### 4️⃣ Walidacja przed wysłaniem

```python
def send_uart_command(addr, cmd_h, cmd_l, data=[]):
    # Walidacja
    assert 0 <= addr <= 255
    assert 0 <= cmd_h <= 255
    assert 0 <= cmd_l <= 255
    assert all(0 <= b <= 255 for b in data)
    
    # Wysłanie
    return requests.post(
        "http://localhost:8000/uart/send",
        json={"addr": addr, "cmd_h": cmd_h, "cmd_l": cmd_l, "data": data}
    )
```

---

## 🛠️ Rozszerzanie API

### Dodanie nowego endpointa

```python
@app.get("/custom/endpoint")
async def custom_endpoint():
    """Własny endpoint"""
    return {"message": "Hello from custom endpoint"}
```

### Dodanie middleware

```python
from fastapi import Request
import time

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    logger.info(f"{request.method} {request.url.path} - {duration:.3f}s")
    return response
```

---

## 📚 Zależności

- **FastAPI** - Framework webowy
- **Uvicorn** - Serwer ASGI
- **Pydantic** - Walidacja danych
- **pyserial** - Komunikacja UART (przez core)
- **crcmod** - CRC16 (przez core)

Instalacja:
```bash
pip install fastapi uvicorn pydantic pyserial crcmod
```

---

## 🔗 Zobacz też

- [../core/README.md](../core/README.md) - Dokumentacja modułu core
- [../../API.md](../../API.md) - Dokumentacja API użytkownika
- [../../README.md](../../README.md) - Główny README projektu
- [FastAPI Docs](https://fastapi.tiangolo.com/) - Oficjalna dokumentacja FastAPI

---

## 📝 Licencja i autorzy

Moduł napisany dla projektu Dbus Logger - Dbus_Logger.

**Data utworzenia:** 2026-02  
**Framework:** FastAPI  
**Język:** Python 3.8+  
**Serwer:** Uvicorn (ASGI)
