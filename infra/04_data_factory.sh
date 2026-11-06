#!/usr/bin/env bash
# Langkah 4 — Azure Data Factory: linked service, dataset, 3 pipeline, 3 trigger (jalan otomatis).
# Biaya: ~USD 1–2/bulan (orkestrasi + Copy activity DIU=2). TIDAK memakai Data Flow (mahal).
source "$(dirname "$0")/_common.sh"
ext datafactory
# shellcheck disable=SC1091
source "$ROOT/config/.func_host.env"   # FUNC_HOST dari deploy_functions.sh
LAKE_ID="$(az storage account show -n "$SA_LAKE" -g "$RG" --query id -o tsv)"
KV_ID="$(az keyvault show -n "$KV" --query id -o tsv)"

log "Data Factory $ADF"
az datafactory create -g "$RG" -n "$ADF" -l "$LOCATION" --tags "${TAGS[@]}" -o none
ADF_MI="$(az datafactory show -g "$RG" -n "$ADF" --query identity.principalId -o tsv)"
if [[ -z "$ADF_MI" ]]; then   # pastikan system-assigned managed identity aktif
  az resource update --ids "$(az datafactory show -g "$RG" -n "$ADF" --query id -o tsv)" --set identity.type=SystemAssigned -o none
  ADF_MI="$(az datafactory show -g "$RG" -n "$ADF" --query identity.principalId -o tsv)"
fi
assign "$ADF_MI" "Storage Blob Data Contributor" "$LAKE_ID"
assign "$ADF_MI" "Key Vault Secrets User" "$KV_ID"
# Agar storage event trigger bisa membuat Event Grid subscription pada akun lake:
assign "$ME_ID" "EventGrid EventSubscription Contributor" "$LAKE_ID" User
sleep 30

BUILD="$ROOT/build/adf"; rm -rf "$BUILD"; mkdir -p "$BUILD"
START="$(date -u +%Y-%m-%dT%H:%M:%S)"
for f in "$ROOT"/adf/*/*.json; do
  out="$BUILD/$(basename "$(dirname "$f")")__$(basename "$f")"
  sed -e "s#__LAKE__#$SA_LAKE#g" -e "s#__KV__#$KV#g" -e "s#__FUNC_HOST__#$FUNC_HOST#g" \
      -e "s#__LAKE_ID__#$LAKE_ID#g" -e "s#__START__#$START#g" "$f" > "$out"
done

log "Linked services"
for n in ls_adls ls_kv ls_func; do
  az datafactory linked-service create -g "$RG" --factory-name "$ADF" -n "$n" --properties "@$BUILD/linkedService__$n.json" -o none && ok "$n"
done
log "Datasets"
for n in ds_lake_csv ds_lake_parquet; do
  az datafactory dataset create -g "$RG" --factory-name "$ADF" -n "$n" --properties "@$BUILD/dataset__$n.json" -o none && ok "$n"
done
log "Pipelines"
for n in pl_daily_ingest pl_manual_to_parquet pl_weekly_retrain; do
  az datafactory pipeline create -g "$RG" --factory-name "$ADF" -n "$n" --pipeline "@$BUILD/pipeline__$n.json" -o none && ok "$n"
done
log "Triggers"
for n in tr_daily_weekdays tr_weekly_retrain tr_new_manual_file; do
  az datafactory trigger stop -g "$RG" --factory-name "$ADF" -n "$n" -o none 2>/dev/null || true
  az datafactory trigger create -g "$RG" --factory-name "$ADF" -n "$n" --properties "@$BUILD/trigger__$n.json" -o none
  az datafactory trigger start -g "$RG" --factory-name "$ADF" -n "$n" -o none && ok "$n aktif"
done

log "Uji jalankan pipeline harian sekarang"
RUN="$(az datafactory pipeline create-run -g "$RG" --factory-name "$ADF" -n pl_daily_ingest --query runId -o tsv)"
ok "runId=$RUN — pantau di ADF Studio > Monitor, atau:"
echo "  az datafactory pipeline-run show -g $RG --factory-name $ADF --run-id $RUN --query status"
