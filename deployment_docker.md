# Deployment Docker – Raspberry Pi

Instrukcja wdrożenia backendu Dbus Logger na Raspberry Pi OS z wykorzystaniem Docker i Docker Compose.

---

## Spis treści

1. [Wymagania sprzętowe i systemowe](#1-wymagania-sprzętowe-i-systemowe)
2. [Przekierowanie UART na ttyAMA0 – wyłączenie Bluetooth](#2-przekierowanie-uart-na-ttyama0--wyłączenie-bluetooth)
3. [Uprawnienia do portu szeregowego](#3-uprawnienia-do-portu-szeregowego)
4. [Instalacja Docker i Docker Compose](#4-instalacja-docker-i-docker-compose)
5. [Konfiguracja docker-compose.yml](#5-konfiguracja-docker-composeyml)
6. [Pierwsze uruchomienie](#6-pierwsze-uruchomienie)
7. [Podstawowe komendy Docker](#7-podstawowe-komendy-docker)
8. [Logi kontenera](#8-logi-kontenera)
9. [Aktualizacja po zmianach w repo](#9-aktualizacja-po-zmianach-w-repo)
10. [Firewall / sieć](#10-firewall--sieć)
11. [Rozwiązywanie problemów](#11-rozwiązywanie-problemów)

---

## 1. Wymagania sprzętowe i systemowe

| Element | Minimalne wymagania |
|---|---|
| Raspberry Pi | 3B / 3B+ / 4B / 5 |
| System | Raspberry Pi OS Lite lub Desktop (64-bit zalecany) |
| Docker | 20.10+ |
| RAM | 1 GB+ (zalecane dla Docker) |
| Pamięć | 8 GB karta SD (zalecane dla obrazów Docker) |
| Połączenie UART | GPIO 14 (TX) / GPIO 15 (RX) lub adapter USB–UART |

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

Dodaj bieżącego użytkownika do grupy `dialout`, aby Docker mógł uzyskać dostęp do portu szeregowego:

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

## 4. Instalacja Docker i Docker Compose

Na Raspberry Pi (architektura ARM) dostępny jest Docker. Zalecana metoda to oficjalny skrypt instalacyjny Docker Inc.

### 4.1 Instalacja Docker

```bash
# Zaktualizuj listę pakietów
sudo apt update && sudo apt upgrade -y

# Pobierz i uruchom oficjalny skrypt instalacyjny
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
```

Po instalacji dodaj bieżącego użytkownika do grupy `docker`, aby nie musieć używać `sudo`:

```bash
sudo usermod -aG docker $USER
```

> ⚠️ Wyloguj się i zaloguj ponownie (lub uruchom `newgrp docker`), aby zmiany weszły w życie.

### 4.2 Włączenie Docker jako usługi systemowej

```bash
sudo systemctl enable docker
sudo systemctl start docker
```

### 4.3 Instalacja Docker Compose

```bash
sudo apt install -y docker-compose-plugin
```

### 4.4 Weryfikacja instalacji

```bash
# Wersja Dockera
docker --version

# Wersja Docker Compose
docker compose version

# Test działania (powinien pobrać i uruchomić kontener hello-world)
docker run --rm hello-world
```

---

## 5. Konfiguracja docker-compose.yml

Projekt zawiera gotowy plik [docker-compose.yml](docker-compose.yml), który konfiguruje kontener razem z urządzeniem szeregowym, portami i wolumenami.

### 5.1 Domyślna konfiguracja

```yaml
services:
  dbus-logger:
    build: .
    container_name: dbus-logger
    restart: unless-stopped
    devices:
      - /dev/serial0:/dev/serial0    # GPIO UART (zalecane)
      # - /dev/ttyUSB0:/dev/ttyUSB0  # Adapter USB (alternatywnie)
    ports:
      - "8000:8000"
    volumes:
      - ./logs:/app/logs
      - ./app_logs:/app/app_logs
    environment:
      - STATION_ID=${STATION_ID:-raspberrypi}
```

### 5.2 Konfiguracja dla adaptera USB

Jeśli używasz adaptera USB zamiast GPIO, zmień sekcję `devices`:

```yaml
    devices:
      - /dev/ttyUSB0:/dev/ttyUSB0
```

I odpowiednio w pliku `app/core/config.py`:

```python
DEFAULT_PORTS = {
    'linux': '/dev/ttyUSB0',
    ...
}
```

### 5.3 Nadpisanie Station ID

Możesz ustawić `STATION_ID` przez zmienną środowiskową lub plik `.env`.

Plik `.env` w katalogu projektu:
```env
STATION_ID=stanowisko-02
```

Lub przez zmienną przy uruchomieniu:
```bash
STATION_ID=stanowisko-02 docker compose up -d
```

---

## 6. Pierwsze uruchomienie

```bash
# Sklonuj repozytorium
git clone <repo-url>
cd Dbus_Logger_backend_production

# Utwórz katalogi na logi (opcjonalnie - Docker utworzy je automatycznie)
mkdir -p logs app_logs

# Zbuduj obraz i uruchom kontener
docker compose up -d
```

Sprawdź status:
```bash
docker ps
```

Powinieneś zobaczyć kontener `dbus-logger` z statusem `Up`.

---

## 7. Podstawowe komendy Docker

```bash
# Start kontenera
docker compose up -d

# Stop kontenera
docker compose down

# Restart kontenera
docker compose restart

# Logi na żywo
docker compose logs -f

# Zatrzymaj bez usuwania
docker compose stop

# Uruchom ponownie
docker compose start

# Przebuduj obraz (po zmianach w kodzie)
docker compose build --no-cache
docker compose up -d

# Sprawdź zużycie zasobów
docker stats dbus-logger
```

---

## 8. Logi kontenera

### 8.1 Logi na żywo

```bash
# Podgląd logów działającego kontenera (na żywo)
docker logs -f dbus-logger

# Ostatnie 100 linii
docker logs --tail 100 dbus-logger

# Ostatnie 100 linii + na żywo
docker logs --tail 100 -f dbus-logger

# Z timestampami
docker logs -f --timestamps dbus-logger

# Docker Compose
docker compose logs -f
docker compose logs --tail 100 -f
```

### 8.2 Status i inspekcja kontenera

```bash
# Czy kontener działa?
docker ps
docker ps -a          # także zatrzymane

# Szczegółowe informacje (IP, zmienne środowiskowe, urządzenia)
docker inspect dbus-logger

# Zużycie zasobów
docker stats dbus-logger
```

### 8.3 Wejście do kontenera (debugging)

```bash
# Powłoka bash wewnątrz działającego kontenera
docker exec -it dbus-logger bash

# Sprawdzenie dostępnych urządzeń szeregowych wewnątrz kontenera
docker exec dbus-logger ls -la /dev/serial* /dev/ttyAMA* /dev/ttyUSB* 2>/dev/null

# Sprawdzenie health check bezpośrednio z wnątrza
docker exec dbus-logger curl -s http://localhost:8000/health

# Wyjście z kontenera
exit
```

### 8.4 Logi aplikacji (w wolumenach)

Logi zapisywane są w:
- `logs/` – pliki z cyklami UART
- `app_logs/` – logi działania aplikacji (rotacja dzienna)

```bash
# Podgląd ostatniego logu cyklu
ls -lt logs/ | head -5
tail -f logs/<ostatni_plik>.txt

# Logi aplikacji
tail -f app_logs/backend_*.log
```

---

## 9. Aktualizacja po zmianach w repo

Przebieg po każdym `git pull` lub ręcznej edycji plików.

### 9.1 Metoda ręczna

```bash
# Krok 1 – pobierz zmiany
cd ~/Dbus_Logger_backend_production
git pull

# Krok 2 – zatrzymaj kontener
docker compose down

# Krok 3 – przebuduj obraz
docker compose build --no-cache

# Krok 4 – uruchom kontener
docker compose up -d

# Krok 5 – weryfikuj
docker ps
docker logs -f --tail 30 dbus-logger
curl http://localhost:8000/health
```

### 9.2 Skrypt pomocniczy – redeploy.sh

W repozytorium dostępny jest gotowy skrypt [redeploy.sh](redeploy.sh), który wykonuje wszystkie kroki automatycznie.

```bash
# Jednorazowo – nadaj uprawnienia do wykonania
chmod +x redeploy.sh

# Uruchom redeploy
./redeploy.sh

# Opcjonalnie – nadpisz Station ID
STATION_ID=stanowisko-02 ./redeploy.sh
```

Skrypt kolejno:
1. Pobiera zmiany (`git pull`)
2. Tworzy katalogi logów (jeśli nie istnieją)
3. Zatrzymuje stary kontener (`docker compose down`)
4. Buduje nowy obraz (`docker compose build --no-cache`)
5. Uruchamia kontener (`docker compose up -d`)

### 9.3 Wymuszenie nadpisania zmian lokalnych

Jeśli `git pull` zgłasza konflikty:

```bash
# Pobierz aktualny stan remote bez scalania
git fetch origin

# Wymuś nadpisanie lokalnych plików (nieodwracalne!)
git reset --hard origin/main
```

Sprawdź jakie zmiany są lokalnie przed resetem:
```bash
git status
git diff
```

---

## 10. Firewall / sieć

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

## 11. Rozwiązywanie problemów

### `git pull` zgłasza konflikty lub błąd

Na Raspberry Pi pliki mogą różnić się od repozytorium (np. przez ręczne edycje). Aby wymuścić nadpisanie lokalnych zmian wersją z remote:

```bash
# Pobierz aktualny stan remote bez scalania
git fetch origin

# Wymuś nadpisanie lokalnych plików (nieodwracalne!)
git reset --hard origin/main
```

Sprawdź jakie zmiany są lokalnie przed resetem:
```bash
git status
git diff
```

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

# Weryfikacja przynależności do grupy
groups $USER
```

### Kontener nie startuje – błąd urządzenia UART

```bash
# Sprawdź czy urządzenie istnieje na hoście
ls -la /dev/serial0 /dev/ttyAMA0 /dev/ttyUSB0 2>/dev/null

# Sprawdź logi kontenera
docker logs dbus-logger

# Sprawdź czy urządzenie jest zamapowane w kontenerze
docker exec dbus-logger ls -la /dev/serial0 2>/dev/null
```

### Backend nie odpowiada – port zajęty

```bash
# Sprawdź, co zajmuje port 8000 na hoście
sudo ss -tlnp | grep 8000
# lub
sudo lsof -i :8000

# Sprawdź czy kontener działa
docker ps

# Sprawdź nasłuchiwanie wewnątrz kontenera
docker exec dbus-logger netstat -tlnp 2>/dev/null | grep 8000
```

### Backend nie widzi urządzenia UART (timeout danych)

- Sprawdź fizyczne połączenie (TX ↔ RX skrzyżowane).
- Sprawdź zgodność baudrate z urządzeniem docelowym.
- Weryfikacja sygnału przez `minicom` lub `screen` **na hoście** (przed uruchomieniem kontenera):
  ```bash
  sudo apt install minicom
  minicom -D /dev/ttyAMA0 -b 9600
  ```

### Kontener się restartuje w kółko

```bash
# Sprawdź logi – powód restartu
docker logs --tail 100 dbus-logger

# Sprawdź czy aplikacja zwraca błąd przy starcie
docker logs dbus-logger 2>&1 | grep -i error

# Sprawdź health check
docker inspect dbus-logger | grep -A 10 Health
```

### Wolumeny – brak dostępu lub uprawnień

```bash
# Sprawdź uprawnienia do katalogów logs i app_logs na hoście
ls -la logs/ app_logs/

# Jeśli katalogi należą do root – zmień właściciela
sudo chown -R $USER:$USER logs/ app_logs/

# Sprawdź czy wolumeny są zamapowane
docker inspect dbus-logger | grep -A 20 Mounts
```

### Docker Compose nie działa

```bash
# Sprawdź czy jest zainstalowany plugin
docker compose version

# Jeśli brak – zainstaluj
sudo apt install -y docker-compose-plugin

# Alternatywnie – starsza wersja standalone
sudo apt install -y docker-compose
docker-compose --version
```

### Brak odpowiedzi API z sieci

```bash
# Test lokalny na hoście
curl -v http://localhost:8000/health

# Sprawdź firewall
sudo ufw status

# Sprawdź mapowanie portów
docker port dbus-logger

# Test z innego urządzenia w sieci
curl -v http://<IP-raspberry>:8000/health
```
