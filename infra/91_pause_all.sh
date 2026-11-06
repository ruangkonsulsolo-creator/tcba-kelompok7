#!/usr/bin/env bash
# Hentikan semua aktivitas otomatis (mis. setelah penilaian atau saat libur) tanpa menghapus data.
source "$(dirname "$0")/_common.sh"
ext datafactory
for n in tr_daily_weekdays tr_weekly_retrain tr_new_manual_file; do
  az datafactory trigger stop -g "$RG" --factory-name "$ADF" -n "$n" -o none 2>/dev/null && ok "trigger $n berhenti"
done
az ml compute update -n "$AML_COMPUTE" -g "$RG" -w "$AML_WS" --min-instances 0 -o none 2>/dev/null || true
az functionapp stop -g "$RG" -n "$FUNC" -o none && ok "Function App dihentikan (API & dashboard offline)"
echo "Menyalakan kembali: az functionapp start -g $RG -n $FUNC ; az datafactory trigger start ... (lihat 04_data_factory.sh)"
