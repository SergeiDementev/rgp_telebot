# Общее для backup_db.sh и restore_db.sh (docs/hardening_plan.md, этап 3).
# Не запускается сам — подключается командой «source».
#
# Хранилище копий — заменяемое (переменная BACKUP_STORAGE):
#   oci   — Oracle Object Storage, бакет rpg-telebot-backups (на сервере, по умолчанию);
#   local — папка BACKUP_LOCAL_DIR (ручная проверка без реального OCI).
# Остальной путь — копия, проверка, восстановление — одинаков для обоих.

# У cron скудное окружение — PATH задаём сами.
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env}"
LOG_DIR="${LOG_DIR:-$PROJECT_DIR/logs}"

BACKUP_STORAGE="${BACKUP_STORAGE:-oci}"
# Префикс и бакет не менялись с исходного backup_db.sh (docs/notes.md) —
# совместимость с уже загруженными копиями в реальном хранилище.
BACKUP_PREFIX="rpg_backup_"
RETENTION_DAYS=7

OCI_BIN="${OCI_BIN:-/home/ubuntu/.oci-cli-venv/bin/oci}"
OCI_BUCKET="${OCI_BUCKET:-rpg-telebot-backups}"
OCI_NAMESPACE="${OCI_NAMESPACE:-}"
# Неймспейс Object Storage — из .env, не хардкод в скрипте (docs/
# hardening_plan.md, этап 3, п.4): не секрет (имя хранилища аккаунта), но
# раньше был вписан прямо в backup_db.sh, что делало его единственным
# местом правки при смене аккаунта/окружения.
if [[ -z "$OCI_NAMESPACE" && -f "$ENV_FILE" ]]; then
    OCI_NAMESPACE="$(grep -E '^OCI_NAMESPACE=' "$ENV_FILE" | cut -d= -f2- || true)"
fi

# Compose-стек проекта — docker-compose.yml в корне репозитория (не в
# поддиректории, в отличие от «Быков и коров»), поэтому достаточно cd в
# PROJECT_DIR перед вызовом, без явного -f.
compose() {
    (cd "$PROJECT_DIR" && docker compose "$@")
}

# Каждый шаг пишется в журнал с временем и названием шага. При ручном
# запуске из терминала вывод дублируется на экран.
start_log() {
    mkdir -p "$LOG_DIR"
    local log_file="$LOG_DIR/$1"
    if [[ -t 1 ]]; then
        exec > >(tee -a "$log_file") 2>&1
    else
        exec >>"$log_file" 2>&1
    fi
}

STEP="init"
log() {
    echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') [$STEP] $*"
}

# При любом сбое — строка ERROR с названием шага и ненулевой код выхода.
on_error() {
    local exit_code=$?
    log "ERROR: шаг '$STEP' завершился с ошибкой (exit $exit_code)"
    exit "$exit_code"
}

check_tools() {
    command -v docker >/dev/null || { log "ERROR: docker не найден в PATH ($PATH)"; exit 1; }
    case "$BACKUP_STORAGE" in
        oci)
            [[ -x "$OCI_BIN" ]] || { log "ERROR: oci не найден по пути $OCI_BIN"; exit 1; }
            [[ -n "$OCI_NAMESPACE" ]] || { log "ERROR: не задан OCI_NAMESPACE (в .env или окружении)"; exit 1; }
            ;;
        local)
            [[ -n "${BACKUP_LOCAL_DIR:-}" ]] || { log "ERROR: не задан BACKUP_LOCAL_DIR"; exit 1; }
            mkdir -p "$BACKUP_LOCAL_DIR"
            ;;
        *)
            log "ERROR: неизвестное хранилище BACKUP_STORAGE=$BACKUP_STORAGE (oci или local)"
            exit 1
            ;;
    esac
}

# Архив цел и дамп дописан до конца — pg_dump ставит в конце строку-маркер.
verify_dump() {
    gzip -t "$1"
    if ! gzip -dc "$1" | grep -q "PostgreSQL database dump complete"; then
        log "ERROR: дамп неполный — нет маркера 'PostgreSQL database dump complete'"
        exit 1
    fi
}

# --- Хранилище: положить, узнать размер, список, скачать, удалить --------------

oci_os() {
    "$OCI_BIN" os object "$@" --auth instance_principal \
        --bucket-name "$OCI_BUCKET" --namespace "$OCI_NAMESPACE"
}

storage_put() { # <файл> <имя>
    case "$BACKUP_STORAGE" in
        oci) oci_os put --file "$1" --name "$2" >/dev/null ;;
        local) cp "$1" "$BACKUP_LOCAL_DIR/$2" ;;
    esac
}

storage_size() { # <имя> -> размер в байтах
    case "$BACKUP_STORAGE" in
        oci) oci_os head --name "$1" --query '"content-length"' --raw-output ;;
        local) stat -c %s "$BACKUP_LOCAL_DIR/$1" ;;
    esac
}

storage_list() { # -> имена копий, по одному в строке, от старых к новым
    case "$BACKUP_STORAGE" in
        oci)
            oci_os list --prefix "$BACKUP_PREFIX" --all --query 'data[].name' --raw-output \
                | tr -d '[]", ' | grep -v '^$' | sort
            ;;
        local)
            find "$BACKUP_LOCAL_DIR" -maxdepth 1 -name "${BACKUP_PREFIX}*.sql.gz" -printf '%f\n' | sort
            ;;
    esac
}

# Имена + время создания, для ротации (format: "<имя> <ISO8601>" на строку).
storage_list_with_time() {
    case "$BACKUP_STORAGE" in
        oci)
            oci_os list --prefix "$BACKUP_PREFIX" --all --query 'data[].{name:name,created:"time-created"}' --raw-output \
                | python3 -c '
import json, sys
for obj in json.load(sys.stdin):
    print(obj["name"], obj["created"])
'
            ;;
        local)
            # GNU date -r <файл> — время модификации файла (сервер и
            # окружение разработки — оба GNU coreutils).
            while IFS= read -r name; do
                created="$(date -u -r "$BACKUP_LOCAL_DIR/$name" '+%Y-%m-%dT%H:%M:%S.%6NZ')"
                echo "$name $created"
            done < <(storage_list)
            ;;
    esac
}

storage_get() { # <имя> <файл>
    case "$BACKUP_STORAGE" in
        oci) oci_os get --name "$1" --file "$2" >/dev/null ;;
        local) cp "$BACKUP_LOCAL_DIR/$1" "$2" ;;
    esac
}

storage_delete() { # <имя>
    case "$BACKUP_STORAGE" in
        oci) oci_os delete --name "$1" --force >/dev/null ;;
        local) rm -f "$BACKUP_LOCAL_DIR/$1" ;;
    esac
}
