#!/usr/bin/env bash
# Langkah 1 — Resource group, ADLS Gen2 (Bronze/Silver/Gold), Log Analytics + App Insights (dengan batas harian),
# dan BUDGET + ALERT. Biaya: ~USD 0,1–0,5 / bulan.
source "$(dirname "$0")/_common.sh"

log "Resource group $RG"
az group create -n "$RG" -l "$LOCATION" --tags "${TAGS[@]}" -o none && ok "RG siap"
RG_ID="$(az group show -n "$RG" --query id -o tsv)"

log "ADLS Gen2 $SA_LAKE (Standard_LRS, Hot, HNS aktif, tanpa akses publik, tanpa shared key)"
az storage account create -n "$SA_LAKE" -g "$RG" -l "$LOCATION" --sku Standard_LRS --kind StorageV2 \
  --access-tier Hot --enable-hierarchical-namespace true --min-tls-version TLS1_2 \
  --allow-blob-public-access false --allow-shared-key-access false --https-only true \
  --tags "${TAGS[@]}" -o none
LAKE_ID="$(az storage account show -n "$SA_LAKE" -g "$RG" --query id -o tsv)"
assign "$ME_ID" "Storage Blob Data Contributor" "$LAKE_ID" User
warn "Menunggu propagasi role (60 detik)…"; sleep 60
for c in bronze silver gold; do
  az storage fs create -n "$c" --account-name "$SA_LAKE" --auth-mode login -o none 2>/dev/null || true
  ok "container $c"
done

log "Lifecycle: Bronze > 90 hari -> Cool (hemat kapasitas; Bronze tidak pernah diubah)"
cat > /tmp/tcba7_lifecycle.json <<'EOF'
{"rules":[{"enabled":true,"name":"bronze-to-cool","type":"Lifecycle","definition":{
  "filters":{"blobTypes":["blockBlob"],"prefixMatch":["bronze/"]},
  "actions":{"baseBlob":{"tierToCool":{"daysAfterModificationGreaterThan":90}}}}}]}
EOF
az storage account management-policy create --account-name "$SA_LAKE" -g "$RG" --policy @/tmp/tcba7_lifecycle.json -o none && ok "lifecycle aktif"

log "Log Analytics $LAW (retensi 30 hari, batas harian 0,15 GB) + Application Insights $APPI"
ext application-insights
az monitor log-analytics workspace create -g "$RG" -n "$LAW" -l "$LOCATION" --retention-time 30 \
  --quota 0.15 --tags "${TAGS[@]}" -o none
LAW_ID="$(az monitor log-analytics workspace show -g "$RG" -n "$LAW" --query id -o tsv)"
az monitor app-insights component create -g "$RG" -a "$APPI" -l "$LOCATION" --workspace "$LAW_ID" \
  --kind web --application-type web --tags "${TAGS[@]}" -o none
ok "monitoring siap"

log "Budget bulanan USD $BUDGET_AMOUNT dengan alert 25/50/75/100% (aktual) + 100% (prakiraan)"
cat > /tmp/tcba7_budget.json <<EOF
{"properties":{"category":"Cost","amount":${BUDGET_AMOUNT},"timeGrain":"Monthly",
 "timePeriod":{"startDate":"${BUDGET_START}T00:00:00Z","endDate":"${BUDGET_END}T00:00:00Z"},
 "notifications":{
  "a25":{"enabled":true,"operator":"GreaterThan","threshold":25,"thresholdType":"Actual","contactEmails":["${OWNER_EMAIL}"]},
  "a50":{"enabled":true,"operator":"GreaterThan","threshold":50,"thresholdType":"Actual","contactEmails":["${OWNER_EMAIL}"]},
  "a75":{"enabled":true,"operator":"GreaterThan","threshold":75,"thresholdType":"Actual","contactEmails":["${OWNER_EMAIL}"]},
  "a100":{"enabled":true,"operator":"GreaterThan","threshold":100,"thresholdType":"Actual","contactEmails":["${OWNER_EMAIL}"]},
  "f100":{"enabled":true,"operator":"GreaterThan","threshold":100,"thresholdType":"Forecasted","contactEmails":["${OWNER_EMAIL}"]}}}}
EOF
if az rest --method put \
   --url "https://management.azure.com/subscriptions/${SUB_ID}/providers/Microsoft.Consumption/budgets/budget-${PREFIX}?api-version=2023-11-01" \
   --body @/tmp/tcba7_budget.json -o none 2>/tmp/tcba7_budget.err; then
  ok "budget dibuat (cek: Portal > Cost Management > Budgets)"
else
  warn "Budget via API gagal ($(head -c 200 /tmp/tcba7_budget.err)). Buat manual di Portal (panduan Bab 3.4)."
fi
ok "Langkah 1 selesai."
