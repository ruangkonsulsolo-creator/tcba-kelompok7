#!/usr/bin/env bash
# Langkah 3 — Azure Function App (Python 3.11): ingestion, transformasi Silver/Gold, API, pemicu retrain.
# Biaya: Flex Consumption punya kuota gratis bulanan -> praktis USD 0 untuk beban proyek ini.
source "$(dirname "$0")/_common.sh"
LAKE_ID="$(az storage account show -n "$SA_LAKE" -g "$RG" --query id -o tsv)"
KV_ID="$(az keyvault show -n "$KV" --query id -o tsv)"

log "Storage internal Function: $SA_FUNC"
az storage account create -n "$SA_FUNC" -g "$RG" -l "$LOCATION" --sku Standard_LRS --kind StorageV2 \
  --min-tls-version TLS1_2 --allow-blob-public-access false --tags "${TAGS[@]}" -o none

if ! az functionapp show -g "$RG" -n "$FUNC" >/dev/null 2>&1; then
  log "Function App $FUNC (plan: $FUNC_PLAN)"
  if [[ "$FUNC_PLAN" == "flex" ]]; then
    az functionapp create -g "$RG" -n "$FUNC" --storage-account "$SA_FUNC" --flexconsumption-location "$LOCATION" \
      --runtime python --runtime-version 3.11 --instance-memory 2048 --app-insights "$APPI" \
      --tags "${TAGS[@]}" -o none \
    || { warn "Flex gagal di region ini -> fallback Linux Consumption"; FUNC_PLAN=consumption; }
  fi
  if [[ "$FUNC_PLAN" == "consumption" ]]; then
    az functionapp create -g "$RG" -n "$FUNC" --storage-account "$SA_FUNC" --consumption-plan-location "$LOCATION" \
      --os-type Linux --runtime python --runtime-version 3.11 --functions-version 4 --app-insights "$APPI" \
      --tags "${TAGS[@]}" -o none
  fi
fi

log "Managed identity + role"
FUNC_MI="$(az functionapp identity assign -g "$RG" -n "$FUNC" --query principalId -o tsv)"
assign "$FUNC_MI" "Storage Blob Data Contributor" "$LAKE_ID"
assign "$FUNC_MI" "Key Vault Secrets User" "$KV_ID"

log "App settings"
LANG_EP="${LANGUAGE_ENDPOINT:-}"
az functionapp config appsettings set -g "$RG" -n "$FUNC" -o none --settings \
  LAKE_MODE=adls LAKE_ACCOUNT="$SA_LAKE" TARGET_RATIO="$TARGET_RATIO" \
  LANGUAGE_ENDPOINT="$LANG_EP" \
  "LANGUAGE_KEY=@Microsoft.KeyVault(SecretUri=https://${KV}.vault.azure.net/secrets/language-key/)" \
  AML_SUBSCRIPTION_ID="$SUB_ID" AML_RESOURCE_GROUP="$RG" AML_WORKSPACE="$AML_WS" \
  AML_COMPUTE="$AML_COMPUTE" AML_DATASTORE="$AML_DATASTORE" AML_ENVIRONMENT="$AML_ENVIRONMENT"
ok "settings tersimpan"

bash "$(dirname "$0")/deploy_functions.sh"
