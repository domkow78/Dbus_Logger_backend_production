#!/bin/bash
# =============================================================================
# redeploy.sh – Dbus Logger Backend
# Pobiera zmiany z repo, przebudowuje obraz i restartuje kontener.
#
# Użycie:
#   chmod +x redeploy.sh   # jednorazowo, nadanie uprawnień
#   ./redeploy.sh
# =============================================================================

set -e  # Zatrzymaj skrypt przy pierwszym błędzie

CONTAINER_NAME="dbus-logger"
IMAGE_NAME="dbus-logger-backend"
STATION_ID="${STATION_ID:-stanowisko-01}"  # Można nadpisać zmienną środowiskową
DEVICE="/dev/serial0"

echo ""
echo "============================================================"
echo "  Dbus Logger – Redeploy"
echo "============================================================"

# 1. Pobierz zmiany z repozytorium
echo ""
echo "[1/5] git pull..."
git pull

# 2. Utwórz katalogi na logi (jeśli nie istnieją)
echo ""
echo "[2/5] Tworzenie katalogów logs/ i app_logs/..."
mkdir -p logs app_logs

# 3. Zatrzymaj i usuń stary kontener (ignoruj błąd jeśli nie istnieje)
echo ""
echo "[3/5] Zatrzymywanie starego kontenera..."
docker stop "$CONTAINER_NAME" 2>/dev/null || echo "  (kontener '$CONTAINER_NAME' nie był uruchomiony)"
docker rm   "$CONTAINER_NAME" 2>/dev/null || echo "  (kontener '$CONTAINER_NAME' nie istniał)"

# 4. Przebuduj obraz
echo ""
echo "[4/5] Budowanie obrazu Docker..."
docker build -t "$IMAGE_NAME" .

# 5. Uruchom nowy kontener
echo ""
echo "[5/5] Uruchamianie kontenera..."
docker run -d \
  --name "$CONTAINER_NAME" \
  --device "$DEVICE:$DEVICE" \
  -p 8000:8000 \
  -e STATION_ID="$STATION_ID" \
  -e TZ=Europe/Warsaw \
  -v "$(pwd)/logs:/app/logs" \
  -v "$(pwd)/app_logs:/app/app_logs" \
  --restart unless-stopped \
  "$IMAGE_NAME"

echo ""
echo "============================================================"
echo "  Gotowe! Kontener '$CONTAINER_NAME' uruchomiony."
echo "  Station ID: $STATION_ID"
echo "  Device:     $DEVICE"
echo ""
echo "  Logi:       docker logs -f $CONTAINER_NAME"
echo "  Health:     curl http://localhost:8000/health"
echo "============================================================"
echo ""
