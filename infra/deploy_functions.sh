#!/usr/bin/env bash
# Deploy ulang kode Function (jalankan setiap kali kode functions/ atau aml/src/ berubah).
source "$(dirname "$0")/_common.sh"
command -v func >/dev/null || { echo "❌ Azure Functions Core Tools (func) belum terpasang. Lihat panduan Bab 5."; exit 1; }

log "Menyalin aml/src -> functions/aml_src (dipakai endpoint ml_retrain)"
rm -rf "$ROOT/functions/aml_src" && cp -r "$ROOT/aml/src" "$ROOT/functions/aml_src"

log "Publish ke $FUNC (remote build di Azure — tidak memakan ruang disk laptop)"
( cd "$ROOT/functions" && func azure functionapp publish "$FUNC" --python )

log "Menyimpan host key ke Key Vault (dipakai linked service ADF)"
sleep 20
KEY="$(az functionapp keys list -g "$RG" -n "$FUNC" --query functionKeys.default -o tsv)"
az keyvault secret set --vault-name "$KV" -n func-host-key --value "$KEY" -o none
HOST="$(az functionapp show -g "$RG" -n "$FUNC" --query defaultHostName -o tsv)"
echo "FUNC_HOST=$HOST" > "$ROOT/config/.func_host.env"
ok "API: https://$HOST/api/health"
curl -s "https://$HOST/api/health" || true; echo
