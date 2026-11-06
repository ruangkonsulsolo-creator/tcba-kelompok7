"""Memicu retraining di Azure Machine Learning (command job) dari Azure Function.

Dipanggil oleh ADF (pipeline mingguan & pipeline event 'laporan keuangan baru') atau manual
lewat POST /api/ml_retrain. Function memakai Managed Identity -> perlu role
'AzureML Data Scientist' pada workspace (diatur oleh infra/05_aml.sh).
"""
from __future__ import annotations

import datetime as dt
import os

HERE = os.path.dirname(os.path.abspath(__file__))
AML_SRC = os.path.normpath(os.path.join(HERE, "..", "aml_src"))


def submit(trigger: str = "manual") -> dict:
    from azure.ai.ml import Input, MLClient, Output, command
    from azure.identity import DefaultAzureCredential

    ml = MLClient(DefaultAzureCredential(exclude_interactive_browser_credential=True),
                  os.environ["AML_SUBSCRIPTION_ID"], os.environ["AML_RESOURCE_GROUP"], os.environ["AML_WORKSPACE"])
    ds = os.getenv("AML_DATASTORE", "lakegold")
    stamp = dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    job = command(
        code=AML_SRC,
        command=("pip install -q -r requirements.txt && "
                 "python train.py --features ${{inputs.features}} --out ${{outputs.ml}} --trigger " + trigger),
        inputs={"features": Input(type="uri_folder", path=f"azureml://datastores/{ds}/paths/features/", mode="ro_mount")},
        outputs={"ml": Output(type="uri_folder", path=f"azureml://datastores/{ds}/paths/ml/", mode="rw_mount")},
        environment=os.getenv("AML_ENVIRONMENT", "azureml://registries/azureml/environments/sklearn-1.5/labels/latest"),
        compute=os.getenv("AML_COMPUTE", "cpu-cluster"),
        experiment_name=os.getenv("AML_EXPERIMENT", "tcba7-retrain"),
        display_name=f"retrain-{trigger}-{stamp}",
        tags={"trigger": trigger, "project": "tcba7"},
    )
    created = ml.jobs.create_or_update(job)
    return {"job": "ml_retrain", "status": "submitted", "aml_job_name": created.name,
            "studio_url": created.studio_url, "trigger": trigger}
