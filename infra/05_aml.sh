#!/usr/bin/env bash
# Langkah 5 — Azure Machine Learning: workspace, compute cluster (min 0 node), datastore Gold, izin.
# Biaya: workspace USD 0; cluster hanya ditagih saat job berjalan (~USD 0,02–0,05 per retrain).
# JANGAN membuat Compute Instance atau Online Endpoint (ditagih per jam walau idle).
source "$(dirname "$0")/_common.sh"
ext ml
LAKE_ID="$(az storage account show -n "$SA_LAKE" -g "$RG" --query id -o tsv)"
APPI_ID="$(az monitor app-insights component show -g "$RG" -a "$APPI" --query id -o tsv)"

log "Workspace $AML_WS (memakai Application Insights yang sudah ada)"
az ml workspace show -n "$AML_WS" -g "$RG" >/dev/null 2>&1 || \
  az ml workspace create -n "$AML_WS" -g "$RG" -l "$LOCATION" --application-insights "$APPI_ID" \
    --tags "${TAGS[@]}" -o none
WS_ID="$(az ml workspace show -n "$AML_WS" -g "$RG" --query id -o tsv)"
WS_SA_ID="$(az ml workspace show -n "$AML_WS" -g "$RG" --query storage_account -o tsv)"
WS_MI="$(az ml workspace show -n "$AML_WS" -g "$RG" --query identity.principal_id -o tsv)"

log "Compute cluster $AML_COMPUTE ($AML_VM_SIZE, $AML_TIER, 0–1 node, turun ke 0 setelah 120 dtk)"
az ml compute show -n "$AML_COMPUTE" -g "$RG" -w "$AML_WS" >/dev/null 2>&1 || \
  az ml compute create -n "$AML_COMPUTE" -g "$RG" -w "$AML_WS" --type amlcompute --size "$AML_VM_SIZE" \
    --min-instances 0 --max-instances 1 --idle-time-before-scale-down 120 --tier "$AML_TIER" \
    --identity-type system_assigned -o none
CL_MI="$(az ml compute show -n "$AML_COMPUTE" -g "$RG" -w "$AML_WS" --query identity.principal_id -o tsv)"
assign "$CL_MI" "Storage Blob Data Contributor" "$LAKE_ID"     # job membaca features & menulis ml/
assign "$WS_MI" "Storage Blob Data Reader" "$LAKE_ID"          # pratinjau data di Studio

log "Datastore $AML_DATASTORE -> $SA_LAKE/gold (identity-based, tanpa kunci)"
cat > /tmp/tcba7_ds.yml <<EOF
\$schema: https://azuremlschemas.azureedge.net/latest/azureDataLakeGen2.schema.json
name: $AML_DATASTORE
type: azure_data_lake_gen2
description: Lapisan Gold lakehouse TCBA Kelompok 7
account_name: $SA_LAKE
filesystem: gold
EOF
az ml datastore create -f /tmp/tcba7_ds.yml -g "$RG" -w "$AML_WS" -o none && ok "datastore siap"

log "Izin Function App untuk memicu retrain"
FUNC_MI="$(az functionapp identity show -g "$RG" -n "$FUNC" --query principalId -o tsv)"
assign "$FUNC_MI" "AzureML Data Scientist" "$WS_ID"
assign "$FUNC_MI" "Storage Blob Data Contributor" "$WS_SA_ID"   # unggah kode job ke storage workspace

log "Siapkan file job dengan nama datastore/compute yang benar"
sed -e "s#__DS__#$AML_DATASTORE#g" -e "s#__COMPUTE__#$AML_COMPUTE#g" -e "s#__ENV__#$AML_ENVIRONMENT#g" \
  "$ROOT/aml/job_train.template.yml" > "$ROOT/aml/job_train.yml"
ok "aml/job_train.yml siap. Retrain manual: az ml job create -f aml/job_train.yml -g $RG -w $AML_WS"
