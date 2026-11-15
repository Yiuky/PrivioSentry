# SPDX-License-Identifier: AGPL-3.0-or-later
"""Manifestos de implantação (deploy/k8s, docker-compose): conferências que não precisam de cluster.
A montagem completa é conferida com `kubectl kustomize deploy/k8s` (docs/deploy.md)."""
import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
K8S = os.path.join(ROOT, "deploy", "k8s")


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


def test_kustomization_lists_existing_files():
    kust = read(K8S, "kustomization.yaml")
    for name in re.findall(r"^\s+- (\S+\.(?:yaml|env))\s*$", kust, re.M):
        if name != "secrets.env":  # criado pelo operador a partir do .example (fora do git)
            assert os.path.exists(os.path.join(K8S, name)), name
    assert os.path.exists(os.path.join(K8S, "secrets.env.example"))


def test_app_is_single_replica_recreate_with_health_probes_and_no_root():
    app = read(K8S, "app.yaml")
    assert re.search(r"replicas: 1\b", app) and "type: Recreate" in app       # estado em memória: 1 réplica
    assert app.count("path: /healthz") == 2
    assert "runAsNonRoot: true" in app and "fsGroup: 10001" in app and "allowPrivilegeEscalation: false" in app
    assert "automountServiceAccountToken: false" in app


def test_network_is_closed_by_default_and_external_ai_stays_off():
    net = read(K8S, "networkpolicy.yaml")
    assert "name: padrao-nega-tudo" in net and 'policyTypes: ["Ingress", "Egress"]' in net
    config = read(K8S, "config.env")
    assert "AI_ALLOW_EXTERNAL=0" in config
    for key in ("PRIVIO_TASKS_FILE", "PRIVIO_SETTINGS_FILE", "PRIVIO_DOC_TEMPLATES_DIR", "PRIVIO_OUTPUT_DIR"):
        assert re.search(rf"^{key}=/data/", config, re.M), key                 # tudo no volume, nada na imagem


def test_every_config_variable_is_documented():
    docs = read(ROOT, "docs", "configuration.md")
    for key in re.findall(r"^([A-Z_]+)=", read(K8S, "config.env"), re.M):
        assert f"`{key}`" in docs, key


def test_secrets_never_go_to_git_or_the_image():
    assert "deploy/k8s/secrets.env" in read(ROOT, ".gitignore").split()
    assert "deploy/k8s/secrets.env" in read(ROOT, ".dockerignore").split()
    if os.path.isdir(os.path.join(ROOT, ".git")):
        tracked = subprocess.run(["git", "ls-files", "deploy/k8s/secrets.env"], cwd=ROOT, capture_output=True,
                                 text=True).stdout
        assert tracked.strip() == ""


def test_compose_keeps_ollama_optional_and_unpublished():
    compose = read(ROOT, "docker-compose.yml")
    block = compose.split("  ollama:", 1)[1].split("\nvolumes:", 1)[0]
    assert 'profiles: ["ollama"]' in block and "ports:" not in block
