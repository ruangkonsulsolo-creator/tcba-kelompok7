#!/usr/bin/env bash
# Langkah 2 — Key Vault (RBAC) + Azure AI Language tier F0 (GRATIS 5.000 dokumen/bulan).
source "$(dirname "$0")/_common.sh"

log "Key Vault $KV"
az keyvault create -n "$KV" -g "$RG" -l "$LOCATION" --enable-rbac-authorization true \
  --retention-days 7 --tags "${TAGS[@]}" -o none
KV_ID="$(az keyvault show -n "$KV" --query id -o tsv)"
assign "$ME_ID" "Key Vault Secrets Officer" "$KV_ID" User
sleep 30

log "Azure AI Language $LANG_NAME (F0)"
if ! az cognitiveservices account show -n "$LANG_NAME" -g "$RG" >/dev/null 2>&1; then
  az cognitiveservices account create -n "$LANG_NAME" -g "$RG" -l "$LOCATION" --kind TextAnalytics \
    --sku F0 --custom-domain "$LANG_NAME" --yes --tags "${TAGS[@]}" -o none \
  || { warn "F0 gagal (hanya boleh 1 F0 per subscription). Pilihan: pakai yang sudah ada, atau lewati — pipeline otomatis memakai leksikon."; exit 0; }
fi
LANG_EP="$(az cognitiveservices account show -n "$LANG_NAME" -g "$RG" --query properties.endpoint -o tsv)"
LANG_KEY="$(az cognitiveservices account keys list -n "$LANG_NAME" -g "$RG" --query key1 -o tsv)"
az keyvault secret set --vault-name "$KV" -n language-key --value "$LANG_KEY" -o none
echo "LANGUAGE_ENDPOINT=$LANG_EP" >> "$STATE"
ok "endpoint: $LANG_EP  (kunci disimpan di Key Vault: language-key)"
