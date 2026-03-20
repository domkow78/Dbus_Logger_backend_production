# Deployment – Raspberry Pi

Instrukcja wdrożenia backendu Dbus Logger na Raspberry Pi OS (Bullseye / Bookworm).

---

## Spis treści

1. [Wymagania sprzętowe i systemowe](#1-wymagania-sprzętowe-i-systemowe)
2. [Przekierowanie UART na ttyAMA0 – wyłączenie Bluetooth](#2-przekierowanie-uart-na-ttyama0--wyłączenie-bluetooth)
3. [Uprawnienia do portu szeregowego](#3-uprawnienia-do-portu-szeregowego)
4. [Instalacja backendu](#4-instalacja-backendu)
5. [Konfiguracja portu UART w aplikacji](#5-konfiguracja-portu-uart-w-aplikacji)
6. [Uruchomienie ręczne (testowe)](#6-uruchomienie-ręczne-testowe)
7. [Usługa systemd – autostart przy starcie systemu](#7-usługa-systemd--autostart-przy-starcie-systemu)
8. [Weryfikacja działania](#8-weryfikacja-działania)
9. [Docker (opcjonalnie)](#9-docker-opcjonalnie)
10. [Logi kontenera Docker](#10-logi-kontenera-docker)
11. [Aktualizacja po zmianach w repo](#11-aktualizacja-po-zmianach-w-repo)
12. [Firewall / sieć](#12-firewall--sieć)
13. [Rozwiązywanie problemów](#13-rozwiązywanie-problemów)

---

## 1. Wymagania sprzętowe i systemowe

| Element | Minimalne wymagania |
|---|---|
| Raspberry Pi | 3B / 3B+ / 4B / 5 |
| System | Raspberry Pi OS Lite lub Desktop (64-bit zalecany) |
| Python | 3.10 lub nowszy |
| RAM | 512 MB (1 GB+ zalecane) |
| Pamięć | 4 GB karta SD |
| Połączenie UART | GPIO 14 (TX) / GPIO 15 (RX) lub adapter USB–UART |

Sprawdź wersję Pythona:
```bash
python3 --version
```

---

## 2. Przekierowanie UART na ttyAMA0 – wyłączenie Bluetooth

Na Raspberry Pi sprzętowy port UART (GPIO 14/15) jest domyślnie zajęty przez moduł **Bluetooth** (`/dev/ttyAMA0`), a do GPIO wyprowadzony jest minimalny UART mini (`/dev/ttyS0`), który jest mniej stabilny (wrażliwy na zmianę częstotliwości zegara rdzenia).

Aby uzyskać pełny, stabilny UART na GPIO 14/15 jako `/dev/ttyAMA0`, należy **wyłączyć Bluetooth**.

### 2.1 Edycja pliku konfiguracyjnego boot

> **Raspberry Pi OS Bookworm (2023+):**
> ```bash
> sudo nano /boot/firmware/config.txt
> ```
>
> **Raspberry Pi OS Bullseye i starsze:**
> ```bash
> sudo nano /boot/config.txt
> ```

Na końcu pliku dodaj:
```ini
# Wyłącz Bluetooth – zwolnij ttyAMA0 dla GPIO UART
dtoverlay=disable-bt
```

Zapisz plik: `Ctrl+O` → `Enter` → `Ctrl+X`.

### 2.2 Wyłączenie usługi hciuart

```bash
sudo systemctl disable hciuart
sudo systemctl stop hciuart
```

### 2.3 Wyłączenie konsoli szeregowej (jeśli włączona)

Upewnij się, że system nie używa UART jako terminala logowania:

```bash
sudo raspi-config
```

Przejdź do:
```
Interface Options → Serial Port
  "Would you like a login shell to be accessible over serial?" → No
  "Would you like the serial port hardware to be enabled?"     → Yes
```

Alternatywnie ręcznie – usuń `console=serial0,115200` z linii kernel w:
```bash
sudo nano /boot/cmdline.txt
# lub (Bookworm)
sudo nano /boot/firmware/cmdline.txt
```

### 2.4 Restart

```bash
sudo reboot
```

### 2.5 Weryfikacja po restarcie

```bash
# Sprawdź dostępne porty szeregowe
ls -la /dev/serial* /dev/ttyAMA* /dev/ttyS0 2>/dev/null

# Oczekiwany wynik:
# lrwxrwxrwx ... /dev/serial0 -> ttyAMA0
# lrwxrwxrwx ... /dev/serial1 -> ttyS0
# crw-rw---- ... /dev/ttyAMA0

# Sprawdź, że Bluetooth nie zajmuje UART
systemctl status hciuart
# Powinno pokazać: disabled / inactive
```

---

## 3. Uprawnienia do portu szeregowego

Dodaj bieżącego użytkownika do grupy `dialout`, aby mógł korzystać z portu szeregowego bez `sudo`:

```bash
sudo usermod -a -G dialout $USER
```

Wyloguj się i zaloguj ponownie (lub uruchom `newgrp dialout`), aby zmiany weszły w życie.

Weryfikacja:
```bash
groups $USER
# Powinno zawierać: dialout
```

---

## 4. Instalacja backendu

```bash
# 1. Klonowanie repozytorium
git clone <repo-url>
cd Dbus_Logger_backend_production

# 2. Aktualizacja pip i narzędzi
python3 -m pip install --upgrade pip

# 3. Utwórz środowisko wirtualne
python3 -m venv venv

# 4. Aktywuj środowisko
source venv/bin/activate

# 5. Zainstaluj zależności
pip install -r requirements.txt
```

Opcjonalnie – auto-discovery w sieci LAN (mDNS):
```bash
pip install zeroconf
```

---

## 5. Konfiguracja portu UART w aplikacji

Otwórz plik [app/core/config.py](app/core/config.py) i upewnij się, że domyślny port dla Linuxa wskazuje na właściwy port.

Jeśli używasz **GPIO UART przez symlink `/dev/serial0`** (zalecane):
```python
DEFAULT_PORTS = {
    'linux': '/dev/serial0',   # ← symlink Pi OS → ttyAMA0 (stabilny, działa również w Docker)
    ...
}
```

Jeśli chcesz użyć **ttyAMA0 bezpośrednio**:
```python
DEFAULT_PORTS = {
    'linux': '/dev/ttyAMA0',   # ← hardware UART na GPIO 14/15
    ...
}
```

Jeśli używasz **adaptera USB–UART**:
```python
DEFAULT_PORTS = {
    'linux': '/dev/ttyUSB0',   # ← adapter USB
    ...
}
```

Alternatywnie możesz ustawić port przez zmienną środowiskową (jeśli aplikacja to obsługuje) lub przez endpoint API `/config` w trakcie działania.

Sprawdź również parametry transmisji – domyślne wartości w `config.py`:

| Parametr | Wartość domyślna |
|---|---|
| Baudrate | `9600` |
| Bytesize | `8` |
| Parity | `N` (brak) |
| Stopbits | `1` |
| Timeout | `1.0 s` |

---

## 6. Uruchomienie ręczne (testowe)

```bash
cd ~/Dbus_Logger_backend_production
source venv/bin/activate

python start_backend.py
```

Backend powinien uruchomić się na porcie **8000**:
```
======================================================================
🚀 DBUS LOGGER - BACKEND
======================================================================
Station ID:       raspberrypi
Local IP:         192.168.x.x

Backend dostępny na:
  • API:          http://192.168.x.x:8000
  • API Docs:     http://192.168.x.x:8000/docs
  • Health Check: http://192.168.x.x:8000/health
======================================================================
```

Zatrzymaj: `Ctrl+C`

---

## 7. Usługa systemd – autostart przy starcie systemu

Utwórz plik serwisu:

```bash
sudo nano /etc/systemd/system/dbus-logger-backend.service
```

Wklej poniższą konfigurację (dostosuj ścieżki i użytkownika):

```ini
[Unit]
Description=Dbus Logger Backend
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/Dbus_Logger_backend_production
ExecStart=/home/pi/Dbus_Logger_backend_production/venv/bin/python start_backend.py
Restart=on-failure
RestartSec=5s

# Opcjonalnie: ID stanowiska
# Environment=STATION_ID=stanowisko-01

StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

> ⚠️ Zamień `pi` na rzeczywistą nazwę użytkownika jeśli jest inna (`whoami`).  
> ⚠️ Dostosuj ścieżkę `/home/pi/...` do rzeczywistego miejsca klonowania.

Załaduj i włącz serwis:

```bash
# Przeładuj konfigurację systemd
sudo systemctl daemon-reload

# Włącz autostart
sudo systemctl enable dbus-logger-backend.service

# Uruchom serwis
sudo systemctl start dbus-logger-backend.service

# Sprawdź status
sudo systemctl status dbus-logger-backend.service
```

Podgląd logów na żywo:
```bash
journalctl -u dbus-logger-backend.service -f
```

---

## 8. Weryfikacja działania

```bash
# Health check
curl http://localhost:8000/health

# Lista dostępnych portów
curl http://localhost:8000/ports

# Dokumentacja API (w przeglądarce)
# http://<IP-raspberry>:8000/docs
```

---

## 9. Docker (opcjonalnie)

Na Raspberry Pi (architektura ARM) dostępny jest Docker. Wymaga dostępu do portu szeregowego wewnątrz kontenera – konieczne jest przekazanie urządzenia.

```bash
# Utwórz katalogi na logi przed pierwszym uruchomieniem
# (Docker tworzy je automatycznie jako root – lepiej zrobić to ręcznie)
mkdir -p logs app_logs

# Budowanie obrazu
docker build -t dbus-logger-backend .

# Uruchomienie z dostępem do GPIO UART
docker run -d \
  --name dbus-logger \
  --device /dev/serial0:/dev/serial0 \
  -p 8000:8000 \
  -e STATION_ID=stanowisko-01 \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/app_logs:/app/app_logs \
  --restart unless-stopped \
  dbus-logger-backend

# Dla adaptera USB
docker run -d \
  --name dbus-logger \
  --device /dev/ttyUSB0:/dev/ttyUSB0 \
  -p 8000:8000 \
  --restart unless-stopped \
  dbus-logger-backend
```

> ℹ️ Użytkownik wewnątrz kontenera musi należeć do grupy `dialout` lub kontener uruchamiamy z `--privileged` (niezalecane produkcyjnie).

---

## 10. Logi kontenera Docker

### Logi na żywo

```bash
# Podgląd logów działającego kontenera (na żywo)
docker logs -f dbus-logger

# Ostatnie 100 linii
docker logs --tail 100 dbus-logger

# Ostatnie 100 linii + na żywo
docker logs --tail 100 -f dbus-logger

# Z timestampami
docker logs -f --timestamps dbus-logger
```

### Status i inspekcja kontenera

```bash
# Czy kontener działa?
docker ps
docker ps -a          # także zatrzymane

# Szczegółowe informacje (IP, zmienne środowiskowe, urządzenia)
docker inspect dbus-logger

# Zużycie zasobów
docker stats dbus-logger
```

### Wejście do kontenera (debugging)

```bash
# Powłoka bash wewnątrz działającego kontenera
docker exec -it dbus-logger bash

# Sprawdzenie dostępnych urządzeń szeregowych wewnątrz kontenera
docker exec dbus-logger ls -la /dev/serial* /dev/ttyAMA* /dev/ttyUSB* 2>/dev/null

# Sprawdzenie health check bezpośrednio z wnątrza
docker exec dbus-logger curl -s http://localhost:8000/health
```

---

## 11. Aktualizacja po zmianach w repo

Przebieg po każdym `git pull` lub ręcznej edycji plików:

### Krok 1 – pobierz zmiany

```bash
cd ~/Dbus_Logger_backend_production
git pull
```

### Krok 2 – zatrzymaj i usuń stary kontener

```bash
docker stop dbus-logger
docker rm dbus-logger
```

### Krok 3 – przebuduj obraz

```bash
docker build -t dbus-logger-backend .
```

> ⚠️ Jeśli zmieniłeś tylko pliki Python (nie `requirements.txt` ani `Dockerfile`), można przyspieszyć build dodając `--cache-from dbus-logger-backend`.

### Krok 4 – uruchom nowy kontener

```bash
docker run -d \
  --name dbus-logger \
  --device /dev/serial0:/dev/serial0 \
  -p 8000:8000 \
  -e STATION_ID=stanowisko-01 \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/app_logs:/app/app_logs \
  --restart unless-stopped \
  dbus-logger-backend
```

> ℹ️ Flaga `--restart unless-stopped` sprawi, że kontener będzie się automatycznie wznawiał po restarcie Raspberry Pi (bez potrzeby konfigurowania systemd).

### Krok 5 – zweryfikuj

```bash
# Sprawdź czy kontener ruszył
docker ps

# Obserwuj logi startu
docker logs -f --tail 30 dbus-logger

# Health check
curl http://localhost:8000/health
```

### Skrypt pomocniczy – jednolinijkowy redeploy

```bash
git pull \
  ; docker stop dbus-logger \
  ; docker rm dbus-logger \
  ; docker build -t dbus-logger-backend . \
  ; docker run -d \
      --name dbus-logger \
      --device /dev/serial0:/dev/serial0 \
      -p 8000:8000 \
      -e STATION_ID=stanowisko-01 \
      -v $(pwd)/logs:/app/logs \
      -v $(pwd)/app_logs:/app/app_logs \
      --restart unless-stopped \
      dbus-logger-backend
```

---

## 12. Firewall / sieć

Upewnij się, że port `8000` jest dostępny w sieci LAN:

```bash
# Sprawdź status firewalla
sudo ufw status

# Jeśli firewall aktywny – zezwól na port 8000
sudo ufw allow 8000/tcp
sudo ufw reload
```

Backend nasłuchuje na `0.0.0.0:8000` – dostępny ze wszystkich interfejsów sieciowych.

---

## 13. Rozwiązywanie problemów

### Port `/dev/ttyAMA0` nie istnieje lub niedostępny

```bash
# Sprawdź czy dtoverlay=disable-bt jest w config.txt
grep "disable-bt" /boot/firmware/config.txt

# Sprawdź, czy hciuart jest wyłączony
systemctl is-enabled hciuart

# Sprawdź urządzenia szeregowe
dmesg | grep -i tty
```

### Brak uprawnień do portu szeregowego

```bash
# Sprawdź właściciela urządzenia
ls -la /dev/ttyAMA0
# Powinno pokazać: crw-rw---- ... root dialout ...

# Dodaj użytkownika do grupy dialout i zaloguj ponownie
sudo usermod -a -G dialout $USER
```

### Backend nie startuje – błąd portu zajętego

```bash
# Sprawdź, co zajmuje port 8000
sudo ss -tlnp | grep 8000
# lub
sudo lsof -i :8000
```

### Backend nie widzi urządzenia UART (timeout danych)

- Sprawdź fizyczne połączenie (TX ↔ RX skrzyżowane).
- Sprawdź zgodność baudrate z urządzeniem docelowym (`DEFAULT_BAUDRATE` w `config.py`).
- Weryfikacja sygnału przez `minicom` lub `screen`:
  ```bash
  sudo apt install minicom
  minicom -D /dev/ttyAMA0 -b 9600
  ```

### Logi aplikacji

Logi zapisywane są w:
- `logs/` – pliki z cyklami UART
- `app_logs/` – logi działania aplikacji (rotacja dzienna)

```bash
# Podgląd ostatniego logu cyklu
ls -lt logs/ | head -5
tail -f logs/<ostatni_plik>.txt
```
