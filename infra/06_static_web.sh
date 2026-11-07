#!/usr/bin/env bash
# Langkah 6 — Dashboard web (UI tabel + grafik) di Azure Storage Static Website. Biaya ~USD 0,01/bulan.
source "$(dirname "$0")/_common.sh"
# shellcheck disable=SC1091
load_func_host

log "Storage static website $SA_WEB"
az storage account create -n "$SA_WEB" -g "$RG" -l "$LOCATION" --sku Standard_LRS --kind StorageV2 \
  --min-tls-version TLS1_2 --allow-blob-public-access false --tags "${TAGS[@]}" -o none
WEB_ID="$(az storage account show -n "$SA_WEB" -g "$RG" --query id -o tsv)"
assign "$ME_ID" "Storage Blob Data Contributor" "$WEB_ID" User
sleep 30
az storage blob service-properties update --account-name "$SA_WEB" --static-website \
  --index-document index.html --404-document index.html --auth-mode login -o none

log "Mengisi web/config.js dengan alamat API dan mengunggah"
TMP="$(mktemp -d)"; cp -r "$ROOT/web/." "$TMP/"
echo "window.TCBA_API_BASE = \"https://$FUNC_HOST\";" > "$TMP/config.js"
az storage blob upload-batch -s "$TMP" -d '$web' --account-name "$SA_WEB" --auth-mode login --overwrite -o none
URL="$(az storage account show -n "$SA_WEB" -g "$RG" --query primaryEndpoints.web -o tsv)"

log "CORS Function App -> ${URL%/}"
az functionapp cors add -g "$RG" -n "$FUNC" --allowed-origins "${URL%/}" -o none || true
ok "Dashboard: $URL"
