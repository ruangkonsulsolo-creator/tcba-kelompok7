#!/usr/bin/env bash
# OPSIONAL — Synapse serverless SQL untuk kueri SQL di atas Parquet Gold (Power BI / SSMS).
# Biaya: workspace USD 0 + USD 5 per TB data dipindai (data proyek ini KB–MB -> ~USD 0).
# JANGAN membuat Dedicated SQL pool atau Spark pool.
source "$(dirname "$0")/_common.sh"
ext synapse
LAKE_ID="$(az storage account show -n "$SA_LAKE" -g "$RG" --query id -o tsv)"
az storage fs create -n synapse --account-name "$SA_LAKE" --auth-mode login -o none 2>/dev/null || true
PASS="Tcba7!$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 14)"
log "Synapse workspace $SYN"
az synapse workspace create -n "$SYN" -g "$RG" -l "$LOCATION" --storage-account "$SA_LAKE" --file-system synapse \
  --sql-admin-login-user sqladmintcba --sql-admin-login-password "$PASS" --tags "${TAGS[@]}" -o none
az keyvault secret set --vault-name "$KV" -n synapse-sql-admin --value "$PASS" -o none
MYIP="$(curl -s https://api.ipify.org || echo 0.0.0.0)"
az synapse workspace firewall-rule create --workspace-name "$SYN" -g "$RG" -n myip \
  --start-ip-address "$MYIP" --end-ip-address "$MYIP" -o none
SYN_MI="$(az synapse workspace show -n "$SYN" -g "$RG" --query identity.principalId -o tsv)"
assign "$SYN_MI" "Storage Blob Data Reader" "$LAKE_ID"
ok "Buka Synapse Studio, jalankan sql/synapse_views.sql pada 'Built-in' (serverless)."
echo "Endpoint serverless: $SYN-ondemand.sql.azuresynapse.net (password admin di Key Vault: synapse-sql-admin)"
