#!/usr/bin/env bash
# Бэкап БД в Object Storage (docs/hardening_plan.md, этап 3 — общий код
# с restore_db.sh вынесен в backup_common.sh, см. его докстринг про
# переключаемое хранилище BACKUP_STORAGE=oci|local).
#
# pg_dump из контейнера db (docker compose) | gzip -> временный файл ->
# загрузка в хранилище -> удаление локального файла -> ротация:
# удаляются бэкапы старше 7 дней (по времени создания).
#
# Каждый шаг пишется в logs/backup.log. При ручном запуске из терминала
# вывод дублируется на экран. При сбое — строка ERROR с названием шага
# и ненулевой exit code.
#
# Запуск: /home/ubuntu/rgp_telebot/db/backup_db.sh (из любой директории).
# Автозапуск — cron пользователя ubuntu, 00:00 UTC (04:00 по Еревану).

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/backup_common.sh"

start_log backup.log
trap on_error ERR
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

log "=== старт бэкапа (хранилище: $BACKUP_STORAGE) ==="

STEP="check"
check_tools

STEP="dump"
BACKUP_NAME="${BACKUP_PREFIX}$(date -u '+%Y-%m-%d_%H%M%S').sql.gz"
BACKUP_PATH="$TMP_DIR/$BACKUP_NAME"
# Учётные данные берутся из окружения самого контейнера db.
compose exec -T db sh -c 'pg_dump --clean --if-exists -U "$POSTGRES_USER" -d "$POSTGRES_DB"' | gzip > "$BACKUP_PATH"
verify_dump "$BACKUP_PATH"
BACKUP_SIZE="$(stat -c %s "$BACKUP_PATH")"
log "дамп готов: $BACKUP_NAME ($BACKUP_SIZE байт)"

STEP="upload"
storage_put "$BACKUP_PATH" "$BACKUP_NAME"
REMOTE_SIZE="$(storage_size "$BACKUP_NAME")"
if [[ "$REMOTE_SIZE" != "$BACKUP_SIZE" ]]; then
    log "ERROR: размер в хранилище ($REMOTE_SIZE) не совпадает с локальным ($BACKUP_SIZE)"
    exit 1
fi
log "загружено в хранилище: $BACKUP_NAME ($REMOTE_SIZE байт, размер сверен)"

STEP="cleanup"
rm -f "$BACKUP_PATH"
log "локальный файл удалён"

STEP="rotate"
CUTOFF_EPOCH="$(( $(date -u +%s) - RETENTION_DAYS * 86400 ))"
EXPIRED="$(storage_list_with_time | python3 -c '
import sys
from datetime import datetime, timezone

cutoff = datetime.fromtimestamp(int(sys.argv[1]), tz=timezone.utc)
for line in sys.stdin:
    name, created_raw = line.split(maxsplit=1)
    created = datetime.fromisoformat(created_raw.strip().replace("Z", "+00:00"))
    if created < cutoff:
        print(name)
' "$CUTOFF_EPOCH")"
if [[ -z "$EXPIRED" ]]; then
    log "устаревших бэкапов (старше $RETENTION_DAYS дн.) нет"
else
    while IFS= read -r name; do
        storage_delete "$name"
        log "удалён устаревший бэкап: $name"
    done <<< "$EXPIRED"
fi

STEP="done"
log "=== бэкап завершён успешно ==="
