#!/usr/bin/env bash
# ==============================================================================
# ScrapeDatAqar - Orchestrated Pipeline Runner
# ==============================================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

echo "=== [1/4] Ensuring FlareSolverr Service ==="
if [ "$(docker ps -q -f name=^/flaresolverr$)" ]; then
    echo "[FOUND] FlareSolverr is active."
elif [ "$(docker ps -aq -f status=exited -f name=^/flaresolverr$)" ]; then
    echo "[STARTING] FlareSolverr container..."
    docker start flaresolverr
    sleep 3
else
    echo "[STARTING] Launching FlareSolverr via docker-compose..."
    docker compose up -d
    sleep 4
fi

echo "=== [2/4] Activating Virtual Environment ==="
if [ ! -d "venv" ]; then
    ./setup_environment.sh
fi
source venv/bin/activate

echo "=== [3/4] Launching Crawler ==="
python3 crawler.py

echo "=== [4/4] Generating Styled Excel Spreadsheet ==="
python3 export_excel.py

echo "=== Pipeline Succeeded! ==="
ls -lh aqar_riyadh_city_53cols.csv aqar_riyadh_city_53cols.xlsx aqar_riyadh_city.db
