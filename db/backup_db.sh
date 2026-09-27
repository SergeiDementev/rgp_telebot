#!/usr/bin/env bash
# Бэкап БД в OCI Object Storage (bucket rpg-telebot-backups).
#
# pg_dump из контейнера db (docker compose) | gzip -> временный файл ->
# oci os object put (--auth instance_principal, без ключей на диске) ->
# удаление локального файла -> ротация: удаляются бэкапы старше 7 дней
# (по time-created из ответа API).
#
# Каждый шаг пишется в logs/backup.log. При ручном запуске из терминала
# вывод дублируется на экран. При сбое — строка ERROR с названием шага
# и ненулевой exit code.
#
# Запуск: /home/ubuntu/rgp_telebot/db/backup_db.sh (из любой директории).
# Автозапуск — cron пользователя ubuntu, 00:00 UTC (04:00 по Еревану).

set -euo pipefail

# У cron скудное окружение — PATH задаём сами, а oci вызываем по полному
# пути внутри venv, не надеясь на ~/.local/bin в PATH.
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
OCI_BIN="${OCI_BIN:-/home/ubuntu/.oci-cli-venv/bin/oci}"

BUCKET="rpg-telebot-backups"
NAMESPACE="frhjbb8niuhf"
RETENTION_DAYS=7
BACKUP_PREFIX="rpg_backup_"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/backup.log"

mkdir -p "$LOG_DIR"
# Весь вывод, включая stderr docker/oci, — в лог. В терминале — ещё и на экран.
if [[ -t 1 ]]; then
    exec > >(tee -a "$LOG_FILE") 2>&1
else
    exec >>"$LOG_FILE" 2>&1
fi

STEP="init"

log() {
    echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') [$STEP] $*"
}

on_error() {
    local exit_code=$?
    log "ERROR: шаг '$STEP' завершился с ошибкой (exit $exit_code), бэкап НЕ выполнен"
    exit "$exit_code"
}
trap on_error ERR

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

log "=== старт бэкапа ==="

STEP="check"
if [[ ! -x "$OCI_BIN" ]]; then
    log "ERROR: oci не найден по пути $OCI_BIN"
    exit 1
fi
if ! command -v docker >/dev/null; then
    log "ERROR: docker не найден в PATH ($PATH)"
    exit 1
fi

STEP="dump"
BACKUP_NAME="${BACKUP_PREFIX}$(date -u '+%Y-%m-%d_%H%M%S').sql.gz"
BACKUP_PATH="$TMP_DIR/$BACKUP_NAME"
cd "$PROJECT_DIR"
# Учётные данные берутся из окружения самого контейнера db.
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' | gzip > "$BACKUP_PATH"
gzip -t "$BACKUP_PATH"
if ! zcat "$BACKUP_PATH" | grep -q "PostgreSQL database dump complete"; then
    log "ERROR: дамп неполный — нет маркера 'PostgreSQL database dump complete'"
    exit 1
fi
BACKUP_SIZE="$(stat -c %s "$BACKUP_PATH")"
log "дамп готов: $BACKUP_NAME ($BACKUP_SIZE байт)"

STEP="upload"
"$OCI_BIN" os object put --auth instance_principal \
    --bucket-name "$BUCKET" --namespace "$NAMESPACE" \
    --file "$BACKUP_PATH" --name "$BACKUP_NAME" >/dev/null
REMOTE_SIZE="$("$OCI_BIN" os object head --auth instance_principal \
    --bucket-name "$BUCKET" --namespace "$NAMESPACE" --name "$BACKUP_NAME" \
    --query '"content-length"' --raw-output)"
if [[ "$REMOTE_SIZE" != "$BACKUP_SIZE" ]]; then
    log "ERROR: размер в bucket ($REMOTE_SIZE) не совпадает с локальным ($BACKUP_SIZE)"
    exit 1
fi
log "загружено в $BUCKET/$BACKUP_NAME ($REMOTE_SIZE байт, размер сверен)"

STEP="cleanup"
rm -f "$BACKUP_PATH"
log "локальный файл удалён"

STEP="rotate"
OBJECTS_JSON="$("$OCI_BIN" os object list --auth instance_principal \
    --bucket-name "$BUCKET" --namespace "$NAMESPACE" \
    --prefix "$BACKUP_PREFIX" --fields name,timeCreated --all)"
EXPIRED="$(python3 -c '
import json, sys
from datetime import datetime, timedelta, timezone

data = json.loads(sys.argv[1] or "{}").get("data", [])
cutoff = datetime.now(timezone.utc) - timedelta(days=int(sys.argv[2]))
for obj in data:
    created = datetime.fromisoformat(obj["time-created"].replace("Z", "+00:00"))
    if created < cutoff:
        print(obj["name"])
' "$OBJECTS_JSON" "$RETENTION_DAYS")"
if [[ -z "$EXPIRED" ]]; then
    log "устаревших бэкапов (старше $RETENTION_DAYS дн.) нет"
else
    while IFS= read -r name; do
        "$OCI_BIN" os object delete --auth instance_principal \
            --bucket-name "$BUCKET" --namespace "$NAMESPACE" \
            --name "$name" --force >/dev/null
        log "удалён устаревший бэкап: $name"
    done <<< "$EXPIRED"
fi

STEP="done"
log "=== бэкап завершён успешно ==="
