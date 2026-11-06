#!/usr/bin/env bash
# Jalankan SETIAP HARI (±10 detik): biaya bulan berjalan + daftar resource yang bisa menguras kredit.
source "$(dirname "$0")/_common.sh"
ext ml >/dev/null 2>&1 || true

log "Biaya bulan berjalan (Cost Management, bisa tertunda 8–24 jam)"
START="$(date -u +%Y-%m-01)"; END="$(date -u +%Y-%m-%d)"
BODY="{\"type\":\"ActualCost\",\"timeframe\":\"Custom\",\"timePeriod\":{\"from\":\"${START}T00:00:00Z\",\"to\":\"${END}T23:59:59Z\"},
\"dataset\":{\"granularity\":\"None\",\"aggregation\":{\"cost\":{\"name\":\"Cost\",\"function\":\"Sum\"}},
\"grouping\":[{\"type\":\"Dimension\",\"name\":\"ServiceName\"}]}}"
az rest --method post --url "https://management.azure.com/subscriptions/$SUB_ID/providers/Microsoft.CostManagement/query?api-version=2023-11-01" \
  --body "$BODY" --query "properties.rows" -o table 2>/dev/null || warn "API biaya tidak tersedia — cek Portal > Cost Management"
echo "Sisa kredit Azure for Students: https://www.microsoftazuresponsorships.com/Balance"

log "Pemeriksaan resource berisiko (harus kosong / 0)"
echo "- AML compute instance (ditagih per jam):"; az ml compute list -g "$RG" -w "$AML_WS" --type computeinstance --query "[].{name:name,state:state}" -o table 2>/dev/null || true
echo "- AML online endpoint (ditagih per jam):";   az ml online-endpoint list -g "$RG" -w "$AML_WS" --query "[].name" -o tsv 2>/dev/null || true
echo "- Konfigurasi cluster (min harus 0):";           az ml compute show -n "$AML_COMPUTE" -g "$RG" -w "$AML_WS" --query "{min:min_instances, max:max_instances, idle_detik:idle_time_before_scale_down, tier:tier}" -o json 2>/dev/null || true
echo "- VM / ACR / App Service Plan non-konsumsi / Synapse pools di RG:"
az resource list -g "$RG" --query "[?type=='Microsoft.Compute/virtualMachines' || type=='Microsoft.ContainerRegistry/registries' || type=='Microsoft.Synapse/workspaces/sqlPools' || type=='Microsoft.Synapse/workspaces/bigDataPools' || type=='Microsoft.MachineLearningServices/workspaces/onlineEndpoints'].{type:type,name:name}" -o table
az appservice plan list -g "$RG" --query "[?sku.tier!='Dynamic' && sku.tier!='FlexConsumption'].{plan:name,tier:sku.tier}" -o table
echo "- Microsoft Defender plan berbayar (harus 'Free'):"
az security pricing list --query "value[?pricingTier=='Standard'].name" -o tsv 2>/dev/null || true
ok "Jika ada yang muncul di atas dan tidak sengaja dibuat: hapus/stop sekarang (panduan Bab 3.6)."
