# Pintasan perintah. Contoh: make setup && make local && make serve
PY ?= .venv/bin/python

setup:            ## buat virtualenv + pasang dependensi (±350 MB)
	python3 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -r requirements-dev.txt

local:            ## pipeline lokal end-to-end dengan data sintetis + 4x retrain (tanpa Azure, gratis)
	$(PY) scripts/run_local_pipeline.py --sample --retrain 4

serve:            ## dashboard + API lokal di http://localhost:8000
	$(PY) scripts/serve_local.py --port 8000

test:             ## uji unit
	$(PY) -m pytest -q

clean-local:      ## hapus lake lokal
	rm -rf _lake

# ---- Azure (jalankan berurutan oleh pemilik akun: Jonnathan) ----
azure-check:  ; bash infra/00_prereq_check.sh
azure-core:   ; bash infra/01_core_storage_budget.sh
azure-kv:     ; bash infra/02_keyvault_language.sh
azure-func:   ; bash infra/03_function_app.sh
azure-adf:    ; bash infra/04_data_factory.sh
azure-aml:    ; bash infra/05_aml.sh
azure-web:    ; bash infra/06_static_web.sh
azure-team:   ; bash infra/07_team_access.sh
deploy-func:  ; bash infra/deploy_functions.sh
cost:         ; bash infra/90_cost_guard.sh
pause:        ; bash infra/91_pause_all.sh

retrain:          ## retrain manual di Azure ML
	. config/project.env; . config/.state.env; az ml job create -f aml/job_train.yml -g $$RG -w mlw-$$PREFIX-$$SUFFIX --set inputs.trigger=manual

.PHONY: setup local serve test clean-local azure-check azure-core azure-kv azure-func azure-adf azure-aml azure-web azure-team deploy-func cost pause retrain
