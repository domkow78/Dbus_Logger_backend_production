#!/bin/bash
# =============================================================================
# redeploy.sh – Dbus Logger Backend
# Pobiera zmiany z repo, przebudowuje obraz i restartuje kontener.
#
# Użycie:
#   chmod +x redeploy.sh        # jednorazowo, nadanie uprawnień
#   ./redeploy.sh
#   STATION_ID=stanowisko-02 ./redeploy.sh
# =============================================================================

set -e  # Zatrzymaj skrypt przy pierwszym błędzie

CONTAINER_NAME="dbus-logger"

echo ""
echo "============================================================"
echo "  Dbus Logger – Redeploy"
echo "============================================================"

# 1. Pobierz zmiany z repozytorium
echo ""
echo "[1/3] git pull..."
git pull

# 2. Utwórz katalogi na logi (jeśli nie istnieją)
echo ""
echo "[2/3] Tworzenie katalogów logs/ i app_logs/..."
mkdir -p logs app_logs

# 3. Przebuduj obraz i uruchom kontener przez Docker Compose
echo ""
echo "[3/3] docker compose up..."
docker compose down
docker compose build --no-cache
docker compose up -d

echo ""
echo "============================================================"
echo "  Gotowe! Kontener '$CONTAINER_NAME' uruchomiony."
echo "  Station ID: ${STATION_ID:-stanowisko-01}"
echo ""
echo "  Logi:       docker logs -f $CONTAINER_NAME"
echo "  Health:     curl http://localhost:8000/health"
echo "============================================================"
echo ""

