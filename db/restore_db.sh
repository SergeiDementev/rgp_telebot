#!/usr/bin/env bash
# Восстановление базы из резервной копии (docs/hardening_plan.md, этап 3).
#
#   db/restore_db.sh                   — список копий в хранилище
#   db/restore_db.sh <имя копии>       — восстановить (спросит подтверждение)
#   db/restore_db.sh <имя копии> --yes — восстановить без вопроса
#
# Что происходит:
#   1. копия скачивается и проверяется (архив цел, дамп полный);
#   2. на всякий случай — копия текущей базы в logs/ (если восстановили не то);
#   3. api и bot останавливаются, чтобы никто не писал в базу во время восстановления;
#   4. база заполняется из копии одной транзакцией: сбой — и база как была;
#   5. api и bot запускаются обратно, скрипт ждёт, пока API станет healthy.
#
# Журнал — logs/restore.log. Хранилище — BACKUP_STORAGE=oci (по умолчанию)
# или local, см. backup_common.sh.

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/backup_common.sh"

BACKUP_NAME="${1:-}"
CONFIRMED="${2:-}"

if [[ -z "$BACKUP_NAME" ]]; then
    check_tools
    echo "Копии в хранилище ($BACKUP_STORAGE), от старых к новым:"
    storage_list
    exit 0
fi

if [[ "$BACKUP_NAME" != "$BACKUP_PREFIX"*.sql.gz ]]; then
    echo "Имя копии должно быть вида ${BACKUP_PREFIX}ГГГГ-ММ-ДД_ЧЧММСС.sql.gz" >&2
    exit 1
fi

if [[ "$CONFIRMED" != "--yes" ]]; then
    read -r -p "База будет заменена данными из $BACKUP_NAME. Продолжить? [y/N] " answer
    [[ "$answer" == "y" || "$answer" == "Y" ]] || { echo "Отменено."; exit 1; }
fi

start_log restore.log
trap on_error ERR
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

log "=== старт восстановления из $BACKUP_NAME (хранилище: $BACKUP_STORAGE) ==="

STEP="check"
check_tools

STEP="download"
BACKUP_PATH="$TMP_DIR/$BACKUP_NAME"
storage_get "$BACKUP_NAME" "$BACKUP_PATH"
verify_dump "$BACKUP_PATH"
log "копия скачана и проверена ($(stat -c %s "$BACKUP_PATH") байт)"

STEP="safety-copy"
SAFETY_PATH="$LOG_DIR/before-restore_$(date -u '+%Y-%m-%d_%H%M%S').sql.gz"
compose exec -T db sh -c 'pg_dump --clean --if-exists -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
    | gzip > "$SAFETY_PATH"
log "текущая база сохранена на случай ошибки: $SAFETY_PATH"

STEP="stop"
compose stop api bot
log "api и bot остановлены"

STEP="restore"
# Если что-то пойдёт не так — api и bot всё равно нужно запустить обратно,
# не оставлять игру недоступной из-за сбоя восстановления.
trap 'log "ERROR: шаг $STEP — запускаю api и bot обратно"; compose start api bot || true; exit 1' ERR
gzip -dc "$BACKUP_PATH" | compose exec -T db sh -c \
    'psql -v ON_ERROR_STOP=1 --single-transaction --quiet -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
    >/dev/null
log "база восстановлена"

STEP="start"
compose start api bot
API_CONTAINER="$(compose ps -q api)"
STATUS=""
for _ in $(seq 1 60); do
    STATUS="$(docker inspect -f '{{.State.Health.Status}}' "$API_CONTAINER")"
    [[ "$STATUS" == "healthy" ]] && break
    sleep 2
done
if [[ "$STATUS" != "healthy" ]]; then
    log "ERROR: API не стал healthy за 2 минуты (состояние: $STATUS) — смотрите логи api"
    exit 1
fi
log "api и bot запущены, API healthy"

STEP="done"
log "=== восстановление завершено успешно ==="
