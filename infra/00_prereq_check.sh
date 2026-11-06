#!/usr/bin/env bash
# Langkah 0 — cek alat, login, region yang diizinkan, dan daftarkan resource provider. GRATIS.
source "$(dirname "$0")/_common.sh"

log "Alat yang terpasang"
for t in az python3 func git; do
  if command -v "$t" >/dev/null; then ok "$t: $($t --version 2>&1 | head -1)"; else warn "$t belum terpasang"; fi
done

log "Akun & subscription aktif"
az account show --query "{subscription:name, id:id, user:user.name, tenant:tenantId}" -o table

log "Kebijakan region (Azure for Students sering membatasi region)"
az policy assignment list --query "[?contains(displayName,'location') || contains(displayName,'Location')].{policy:displayName, params:parameters}" -o json | head -40 || true
echo "Region yang dipakai di config: $LOCATION  (ganti di config/project.env bila ditolak)"

log "Mendaftarkan resource provider (sekali saja, gratis)"
for p in Microsoft.Storage Microsoft.Web Microsoft.DataFactory Microsoft.MachineLearningServices \
         Microsoft.CognitiveServices Microsoft.KeyVault Microsoft.Insights Microsoft.OperationalInsights \
         Microsoft.EventGrid Microsoft.Consumption Microsoft.CostManagement Microsoft.ContainerInstance; do
  az provider register -n "$p" --only-show-errors >/dev/null && echo "  - $p"
done
ok "Selesai. Nama resource yang akan dibuat (sufiks: $SUFFIX):"
printf "  RG=%s\n  Lake=%s\n  Function=%s\n  ADF=%s\n  AML=%s\n  KeyVault=%s\n" "$RG" "$SA_LAKE" "$FUNC" "$ADF" "$AML_WS" "$KV"
