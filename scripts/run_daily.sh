#!/usr/bin/env sh
# Corrida diaria de JobBot para Linux y macOS. Prográmala con cron (`crontab -e`), por ejemplo
# todos los días a las 7:00:
#   0 7 * * * /ruta/a/jobbot/scripts/run_daily.sh
# Usa JOBBOT_HOME si está definida; si no, ~/JobBot.
cd "$(dirname "$0")/.." || exit 1
home_dir="${JOBBOT_HOME:-$HOME/JobBot}"
mkdir -p "$home_dir/data/logs"
log="$home_dir/data/logs/daily-$(date +%Y-%m-%d).log"
# cron arranca con un PATH mínimo: probar las rutas de instalación habituales de uv
PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
echo "=== $(date '+%Y-%m-%dT%H:%M:%S') ===" >> "$log"
uv run jobbot daily >> "$log" 2>&1
