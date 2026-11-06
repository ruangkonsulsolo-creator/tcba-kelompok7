#!/usr/bin/env bash
# HAPUS SEMUA resource proyek (tidak bisa dibatalkan). Unduh dulu data/laporan yang diperlukan!
source "$(dirname "$0")/_common.sh"
read -r -p "Ketik nama resource group ($RG) untuk konfirmasi penghapusan: " ans
[[ "$ans" == "$RG" ]] || { echo "Dibatalkan."; exit 1; }
az ml workspace delete -n "$AML_WS" -g "$RG" --permanently-delete --all-resources --yes 2>/dev/null || true
az group delete -n "$RG" --yes
az keyvault purge -n "$KV" 2>/dev/null || true
az cognitiveservices account purge -n "$LANG_NAME" -g "$RG" -l "$LOCATION" 2>/dev/null || true
ok "Semua resource dihapus."
