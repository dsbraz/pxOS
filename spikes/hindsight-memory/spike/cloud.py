"""Provisionamento explícito somente de recursos dedicados a este spike."""

import json
import secrets
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT = "pxos-spikes"
REGION = "us-central1"
CLUSTER = "hindsight-spike"
NETWORK = "pxos-hindsight-net"
IP_RANGE = "pxos-hindsight-range"
INSTANCE = "primary"
ACCOUNT = "spike-runner@pxos-spikes.iam.gserviceaccount.com"


def gcloud(*args, allow_missing=False):
    result = subprocess.run(
        ["gcloud", *args, "--project=" + PROJECT, "--quiet", "--format=json"],
        text=True,
        capture_output=True,
    )
    if result.returncode:
        if allow_missing and any(
            s in result.stderr for s in ("not found", "NOT_FOUND", "does not exist")
        ):
            return None
        # Nunca incluir argumentos: um comando pode referenciar o arquivo de senha.
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout) if result.stdout.strip() else {}


def provision():
    secret_dir = ROOT / ".secrets"
    secret_dir.mkdir(mode=0o700, exist_ok=True)
    secret_file = secret_dir / "database.json"
    if not secret_file.exists():
        secret_file.write_text(json.dumps({"password": secrets.token_urlsafe(32)}))
        secret_file.chmod(0o600)
    password = json.loads(secret_file.read_text())["password"]
    if gcloud("compute", "networks", "describe", NETWORK, allow_missing=True) is None:
        gcloud("compute", "networks", "create", NETWORK, "--subnet-mode=custom")
    if gcloud("compute", "addresses", "describe", IP_RANGE, "--global", allow_missing=True) is None:
        gcloud(
            "compute",
            "addresses",
            "create",
            IP_RANGE,
            "--global",
            "--purpose=VPC_PEERING",
            "--prefix-length=16",
            "--network=" + NETWORK,
        )
    connections = gcloud(
        "services",
        "vpc-peerings",
        "list",
        "--network=" + NETWORK,
        "--service=servicenetworking.googleapis.com",
    )
    if not connections:
        gcloud(
            "services",
            "vpc-peerings",
            "connect",
            "--network=" + NETWORK,
            "--ranges=" + IP_RANGE,
            "--service=servicenetworking.googleapis.com",
        )
    print("Rede privada dedicada pronta", flush=True)
    if (
        gcloud("alloydb", "clusters", "describe", CLUSTER, "--region=" + REGION, allow_missing=True)
        is None
    ):
        flags = secret_dir / "cluster-flags.json"
        flags.write_text(json.dumps({"--password": password}))
        flags.chmod(0o600)
        try:
            gcloud(
                "alloydb",
                "clusters",
                "create",
                CLUSTER,
                "--region=" + REGION,
                "--network=" + NETWORK,
                "--allocated-ip-range-name=" + IP_RANGE,
                "--database-version=POSTGRES_16",
                "--disable-automated-backup",
                "--flags-file=" + str(flags),
            )
        finally:
            flags.unlink(missing_ok=True)
    print("Cluster AlloyDB pronto", flush=True)
    if (
        gcloud(
            "alloydb",
            "instances",
            "describe",
            INSTANCE,
            "--cluster=" + CLUSTER,
            "--region=" + REGION,
            allow_missing=True,
        )
        is None
    ):
        gcloud(
            "alloydb",
            "instances",
            "create",
            INSTANCE,
            "--cluster=" + CLUSTER,
            "--region=" + REGION,
            "--instance-type=PRIMARY",
            "--cpu-count=2",
            "--availability-type=ZONAL",
            "--assign-inbound-public-ip=ASSIGN_IPV4",
            "--database-flags=password.enforce_complexity=on",
        )
    gcloud(
        "projects",
        "add-iam-policy-binding",
        PROJECT,
        "--member=serviceAccount:" + ACCOUNT,
        "--role=roles/alloydb.client",
        "--condition=None",
    )
    state = {
        "project": PROJECT,
        "region": REGION,
        "cluster": CLUSTER,
        "instance": INSTANCE,
        "network": NETWORK,
        "ip_range": IP_RANGE,
        "database": "hindsight_spike",
        "instance_uri": f"projects/{PROJECT}/locations/{REGION}/clusters/{CLUSTER}/instances/{INSTANCE}",
        "service_account": ACCOUNT,
        "connection": "Auth Proxy public IP; no authorized networks",
        "cpu_count": 2,
        "availability": "ZONAL",
    }
    (ROOT / "cloud.json").write_text(json.dumps(state, indent=2) + "\n")
    print("AlloyDB provisionado; metadata em cloud.json", flush=True)


if __name__ == "__main__":
    provision()
