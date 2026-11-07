#!/usr/bin/env bash
# Langkah 7 — Akses anggota tim ke SATU akun (milik Jonnathan). Biaya tetap di akun ini.
# Mode "view" (default): Reader + izin data minimum sesuai tugas masing-masing.
source "$(dirname "$0")/_common.sh"
RG_ID="$(az group show -n "$RG" --query id -o tsv)"
LAKE_ID="$(az storage account show -n "$SA_LAKE" -g "$RG" --query id -o tsv)"
WS_ID="$(az ml workspace show -n "$AML_WS" -g "$RG" --query id -o tsv 2>/dev/null || true)"
WEB_ID="$(az storage account show -n "$SA_WEB" -g "$RG" --query id -o tsv 2>/dev/null || true)"

source "$(dirname "$0")/_invite.sh"

grant_common() {
  assign "$1" "Reader" "$RG_ID" User
  [[ "$TEAM_ROLE_MODE" == "contributor" ]] && assign "$1" "Contributor" "$RG_ID" User
  return 0
}

if [[ -n "$RAIHAN_UPN" ]]; then
  log "Raihan ($RAIHAN_UPN) — Data Source: unggah CSV & data mentah ke Bronze"
  R="$(uid "$RAIHAN_UPN")"
  if [[ -z "$R" ]]; then warn "akun tidak ditemukan di tenant ini — undang sebagai guest (panduan Bab 4.4)"; else
    grant_common "$R"
    assign "$R" "Storage Blob Data Contributor" "$LAKE_ID/blobServices/default/containers/bronze" User
    assign "$R" "Storage Blob Data Reader" "$LAKE_ID" User
  fi
fi
if [[ -n "$RASYID_UPN" ]]; then
  log "Rasyid ($RASYID_UPN) — Preprocessing, ML, Dashboard"
  S="$(uid "$RASYID_UPN")"
  if [[ -z "$S" ]]; then warn "akun tidak ditemukan di tenant ini — undang sebagai guest (panduan Bab 4.4)"; else
    grant_common "$S"
    assign "$S" "Storage Blob Data Reader" "$LAKE_ID" User
    [[ -n "$WS_ID" ]] && assign "$S" "AzureML Data Scientist" "$WS_ID" User
    [[ -n "$WEB_ID" ]] && assign "$S" "Storage Blob Data Contributor" "$WEB_ID" User
  fi
fi
ok "Selesai. Teman login portal.azure.com dengan akunnya, lalu pilih directory/subscription milik Jonnathan."
