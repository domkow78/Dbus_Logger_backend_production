# Dbus Logger – Backend (Production)

REST API backend do monitorowania i logowania komunikacji UART z automatyczną detekcją cykli. Zaprojektowany do uruchomienia na **Raspberry Pi** lub stacji roboczej w sieci LAN. Komunikuje się z dedykowanym frontendem (NiceGUI) przez HTTP.

---

## 📋 Spis treści

- [Architektura](#architektura)
- [Wymagania](#wymagania)
- [Instalacja](#instalacja)
- [Konfiguracja](#konfiguracja)
- [Uruchomienie](#uruchomienie)
- [Endpointy API](#endpointy-api)
- [Struktura projektu](#struktura-projektu)
- [Logi](#logi)
- [Docker](#docker)
- [Zmienne środowiskowe](#zmienne-środowiskowe)

---

## Architektura

```
Raspberry Pi / PC (stanowisko)
┌──────────────────────────────────────────┐
│  start_backend.py                        │
│  ┌──────────────┐   ┌──────────────────┐ │
│  │  FastAPI     │   │ ApplicationService│ │
│  │  :8000       │◄──│  (core_app.py)   │ │
│  └──────────────┘   └────────┬─────────┘ │
│                              │           │
│                    ┌─────────▼─────────┐ │
│                    │ ConnectionManager  │ │
│                    │   (uart.py)        │ │
│                    └─────────┬─────────┘ │
└──────────────────────────────┼───────────┘
                               │ UART (RS-232/USB)
                          [Urządzenie]

PC Operatora
┌────────────────────┐
│  Frontend (NiceGUI)│
│  :8080             │──── HTTP ────► Backend :8000
└────────────────────┘
```

- **`start_backend.py`** – punkt wejścia; uruchamia FastAPI + serwis UART
- **`app/api/main.py`** – REST API (FastAPI), endpointy, CORS
- **`app/core/core_app.py`** – logika biznesowa: detekcja cykli, zapis logów
- **`app/core/uart.py`** – niskopoziomowa obsługa portu szeregowego (pyserial)
- **`app/core/config.py`** – centralna konfiguracja (port, baudrate, ścieżki, reconnect)

---

## Wymagania

- Python **3.10+**
- Dostęp do portu szeregowego (GPIO UART `/dev/ttyAMA0` lub adapter USB, `COM5`)
- Raspberry Pi OS (Linux) lub Windows 10/11

---

## Instalacja

```bash
# 1. Sklonuj repozytorium
git clone <repo-url>
cd Dbus_Logger_backend_production

# 2. Utwórz środowisko wirtualne
python -m venv venv

# Linux/macOS
source venv/bin/activate

# Windows
venv\Scripts\activate

# 3. Zainstaluj zależności
pip install -r requirements.txt
```

**Opcjonalnie** – auto-discovery stanowisk w sieci LAN (mDNS):

```bash
pip install zeroconf
```

---

## Konfiguracja

Wszystkie parametry znajdują się w [app/core/config.py](app/core/config.py).

### Port szeregowy

| System   | Domyślny port   | Alternatywy                              |
|----------|-----------------|------------------------------------------|
| Linux    | `/dev/ttyAMA0`  | `/dev/ttyUSB0`, `/dev/ttyUSB1`, `/dev/serial0` |
| Windows  | `COM5`          | `COM1`, `COM3`, `COM4`                   |

Port jest wykrywany automatycznie na podstawie systemu operacyjnego.

### Parametry UART

| Parametr  | Wartość domyślna |
|-----------|-----------------|
| Baudrate  | `9600`           |
| Data bits | `8`              |
| Parity    | `N` (None)       |
| Stop bits | `1`              |
| Timeout   | `1.0 s`          |

### Auto-reconnect

| Parametr                  | Wartość   | Opis                                         |
|---------------------------|-----------|----------------------------------------------|
| `RECONNECT_ENABLED`       | `True`    | Włącz automatyczne wznawianie połączenia     |
| `RECONNECT_DELAY`         | `2.0 s`   | Opóźnienie między próbami                    |
| `RECONNECT_MAX_ATTEMPTS`  | `0`       | `0` = nieskończone próby                     |
| `RECONNECT_BACKOFF`       | `True`    | Exponential backoff                          |
| `RECONNECT_MAX_DELAY`     | `30.0 s`  | Maksymalne opóźnienie                        |

### Detekcja cykli

Cykl jest wykrywany na podstawie ramki UART z określoną komendą i danymi:

| Zdarzenie | CMD      | DATA      |
|-----------|----------|-----------|
| START     | `0x1001` | `0x01 00` |
| END       | `0x1001` | `0x03 00` |

---

## Uruchomienie

### Tryb produkcyjny (zalecany)

```bash
python start_backend.py
```

Backend uruchomi się na `http://0.0.0.0:8000` (dostępny w całej sieci LAN).

Przy starcie wyświetlany jest banner z adresem IP stanowiska:

```
======================================================================
🚀 DBUS LOGGER - BACKEND
======================================================================
Station ID:       raspberry-01
Hostname:         raspberrypi
Local IP:         192.168.1.42

Backend dostępny na:
  • API:          http://192.168.1.42:8000
  • API Docs:     http://192.168.1.42:8000/docs
  • Health Check: http://192.168.1.42:8000/health
======================================================================
```

### Tryb developerski (uvicorn bezpośrednio)

```bash
uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload
```

### Uruchomienie z własnym ID stanowiska

```bash
STATION_ID=stanowisko-01 python start_backend.py
```

---

## Endpointy API

Interaktywna dokumentacja dostępna pod: `http://<ip>:8000/docs`

| Metoda | Endpoint                      | Opis                                         |
|--------|-------------------------------|----------------------------------------------|
| `GET`  | `/`                           | Strona informacyjna (HTML)                   |
| `GET`  | `/api`                        | Informacje o API (JSON)                      |
| `GET`  | `/health`                     | Health check stanowiska (station_id, UART, uptime) |
| `GET`  | `/status`                     | Status aplikacji i aktywnego cyklu           |
| `GET`  | `/logs`                       | Lista plików logów cykli                     |
| `GET`  | `/logs/{filename}`            | Zawartość logu (JSON)                        |
| `GET`  | `/logs/{filename}/download`   | Pobierz plik logu                            |
| `POST` | `/uart/send`                  | Wyślij ramkę UART                            |
| `GET`  | `/docs`                       | Interaktywna dokumentacja (Swagger UI)       |
| `GET`  | `/redoc`                      | Dokumentacja API (ReDoc)                     |

### Przykład – health check

```bash
curl http://192.168.1.42:8000/health
```

```json
{
  "status": "healthy",
  "station_id": "stanowisko-01",
  "hostname": "raspberrypi",
  "ip_address": "192.168.1.42",
  "uart": {
    "port": "/dev/ttyAMA0",
    "connected": true,
    "baudrate": 9600,
    "reconnect_enabled": true,
    "reconnect_attempts": 0
  },
  "service": {
    "running": true,
    "uptime_seconds": 3621.5,
    "cycles_total": 87,
    "in_cycle": false
  },
  "timestamp": "2026-03-17T10:30:00.123456"
}
```

### Przykład – wysłanie ramki UART

```bash
curl -X POST http://192.168.1.42:8000/uart/send \
  -H "Content-Type: application/json" \
  -d '{"addr": 21, "cmd_h": 16, "cmd_l": 1, "data": [1, 0]}'
```

---

## Struktura projektu

```
Dbus_Logger_backend_production/
├── start_backend.py        # Punkt wejścia (produkcja)
├── requirements.txt        # Zależności Python
├── Dockerfile              # Kontener Docker
├── README.md               # Ten plik
│
├── app/
│   ├── api/
│   │   ├── main.py         # FastAPI app, endpointy REST
│   │   └── README.md       # Dokumentacja modułu API
│   │
│   └── core/
│       ├── config.py       # Konfiguracja (port, baudrate, ścieżki)
│       ├── uart.py         # Obsługa UART, Frame, CRC, ConnectionManager
│       ├── core_app.py     # ApplicationService, CycleDetector, CycleCounter
│       └── README.md       # Dokumentacja modułu core
│
├── logs/                   # Logi cykli (cycle_XXXX_YYYY-MM-DD_HH-MM-SS.txt)
└── app_logs/               # Logi aplikacji (rotacja 1 dzień)
```

---

## Logi

### Logi cykli (`logs/`)

Każdy wykryty cykl generuje osobny plik:

```
logs/cycle_0087_2026-03-17_10-30-00.txt
```

Pliki zawierają wszystkie ramki UART zarejestrowane w trakcie cyklu. Licznik cykli jest persystentny (zapisywany w `logs/.cycle_counter`) i przetrwa restart aplikacji.

### Logi aplikacyjne (`app_logs/`)

Logi procesu backendu (rotacja dzienna, retencja: 1 dzień).

---

## Docker

> Dockerfile jest przygotowany do uzupełnienia. Przykładowe uruchomienie po skonfigurowaniu:

```bash
# Budowanie obrazu
docker build -t dbus-logger-backend .

# Uruchomienie z dostępem do portu szeregowego
docker run -d \
  --name dbus-logger \
  --device /dev/serial0:/dev/serial0 \
  -p 8000:8000 \
  -e STATION_ID=stanowisko-01 \
  -v $(pwd)/logs:/app/logs \
  dbus-logger-backend
```

---

## Zmienne środowiskowe

| Zmienna      | Domyślna             | Opis                                                   |
|--------------|----------------------|--------------------------------------------------------|
| `STATION_ID` | hostname maszyny     | Identyfikator stanowiska widoczny w `/health`          |

---

## Zależności

| Pakiet          | Zastosowanie                              |
|-----------------|-------------------------------------------|
| `fastapi`       | REST API framework                        |
| `uvicorn`       | ASGI server (produkcja)                   |
| `pyserial`      | Obsługa portu szeregowego                 |
| `crcmod`        | Obliczanie CRC16 XModem dla ramek UART    |
| `websockets`    | Wsparcie WebSocket (uvicorn[standard])    |
| `requests`      | Klient HTTP (testy/integracja)            |
| `pytest`        | Testy jednostkowe                         |
| `pytest-cov`    | Pokrycie testami                          |
| `zeroconf`      | *(opcjonalny)* Auto-discovery mDNS w LAN |
