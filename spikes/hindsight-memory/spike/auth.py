"""Prepara ADC isolado por impersonação, sem chave de conta de serviço."""

import argparse
import json
import secrets
from pathlib import Path

from spike.settings import ROOT


def prepare(source):
    credentials = json.loads(source.read_text())
    if credentials.get("type") != "authorized_user":
        raise ValueError("Use o ADC de usuário criado pelo login isolado do spike")
    credentials["quota_project_id"] = "pxos-spikes"
    directory = ROOT / ".secrets"
    directory.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    adc = {
        "type": "impersonated_service_account",
        "service_account_impersonation_url": "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/spike-runner@pxos-spikes.iam.gserviceaccount.com:generateAccessToken",
        "source_credentials": credentials,
        "delegates": [],
        "quota_project_id": "pxos-spikes",
    }
    path = directory / "adc.json"
    # Restrict permissions before writing the credential, including on first creation.
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text(json.dumps(adc))
    path = directory / "api.json"
    if not path.exists():
        path.touch(mode=0o600)
        path.write_text(
            json.dumps({"admin": secrets.token_urlsafe(32), "public": secrets.token_urlsafe(32)})
        )
    print("ADC isolado preparado; conta alvo spike-runner em pxos-spikes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    prepare(parser.parse_args().source)
