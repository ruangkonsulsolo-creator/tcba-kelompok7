#!/usr/bin/env bash
# Dipanggil oleh semua skrip infra: memuat konfigurasi, membuat nama resource yang konsisten.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CFG="$ROOT/config/project.env"
STATE="$ROOT/config/.state.env"
[[ -f "$CFG" ]] || { echo "❌ $CFG belum ada. Jalankan: cp config/project.env.example config/project.env"; exit 1; }
# shellcheck disable=SC1090
source "$CFG"
SUB_ID="$(az account show --query id -o tsv)"
if [[ ! -f "$STATE" ]]; then
  echo "SUFFIX=$(printf '%s-%s' "$SUB_ID" "$PREFIX" | sha1sum | cut -c1-5)" > "$STATE"
fi
# shellcheck disable=SC1090
source "$STATE"

SUB_ID="$(az account show --query id -o tsv)"
TENANT_ID="$(az account show --query tenantId -o tsv)"
ME_ID="$(az ad signed-in-user show --query id -o tsv 2>/dev/null || true)"

SA_LAKE="st${PREFIX}lake${SUFFIX}"     # ADLS Gen2 (Bronze/Silver/Gold)
SA_FUNC="st${PREFIX}fn${SUFFIX}"       # storage internal Azure Functions
SA_WEB="st${PREFIX}web${SUFFIX}"       # static website dashboard
KV="kv-${PREFIX}-${SUFFIX}"
LANG_NAME="lang-${PREFIX}-${SUFFIX}"
LAW="law-${PREFIX}-${SUFFIX}"
APPI="appi-${PREFIX}-${SUFFIX}"
FUNC="func-${PREFIX}-${SUFFIX}"
ADF="adf-${PREFIX}-${SUFFIX}"
AML_WS="mlw-${PREFIX}-${SUFFIX}"
AML_COMPUTE="cpu-cluster"
AML_DATASTORE="lakegold"
SYN="syn-${PREFIX}-${SUFFIX}"
TAGS=(project=tcba-kelompok7 env=dev owner="${OWNER_EMAIL}" course=TCBA)

log()  { printf "\n\033[1;34m▶ %s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m✔ %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m⚠ %s\033[0m\n" "$*"; }

rid() { az resource show -g "$RG" -n "$1" --resource-type "$2" --query id -o tsv; }

# Penugasan peran idempoten (tidak gagal bila sudah ada)
assign() {  # assign <principal-object-id> <role> <scope> [User|Group|ServicePrincipal]
  local who="$1" role="$2" scope="$3" type="${4:-ServicePrincipal}"
  [[ -z "$who" ]] && { warn "principal kosong untuk role $role"; return 0; }
  if az role assignment list --assignee "$who" --role "$role" --scope "$scope" --query "[0].id" -o tsv 2>/dev/null | grep -q .; then
    ok "role '$role' sudah ada"
  else
    az role assignment create --assignee-object-id "$who" --assignee-principal-type "$type" \
      --role "$role" --scope "$scope" -o none && ok "role '$role' diberikan"
  fi
}

ext() { az extension show -n "$1" >/dev/null 2>&1 || az extension add -n "$1" --only-show-errors; }

load_func_host() {
  if [[ -f "$ROOT/config/.func_host.env" ]]; then source "$ROOT/config/.func_host.env"; fi
  if [[ -z "${FUNC_HOST:-}" ]]; then
    FUNC_HOST="$(az functionapp show -g "$RG" -n "$FUNC" --query defaultHostName -o tsv)"; FUNC_HOST="${FUNC_HOST:-$FUNC.azurewebsites.net}"
    echo "FUNC_HOST=$FUNC_HOST" > "$ROOT/config/.func_host.env"
  fi
}
