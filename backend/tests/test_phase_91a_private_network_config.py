"""Phase 91a private-backend-network configuration regressions.

These source-level checks protect the container boundary that TestClient does
not exercise: Uvicorn's Railway-private-network bind and nginx's three
environment-driven proxy surfaces.
"""
from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
START_SH = REPO_ROOT / "backend" / "start.sh"
NGINX_CONF = REPO_ROOT / "frontend" / "nginx.conf"
FRONTEND_DOCKERFILE = REPO_ROOT / "frontend" / "Dockerfile"
DEPLOYMENT = REPO_ROOT / "DEPLOYMENT.md"


def _location_block(config: str, declaration: str) -> str:
    match = re.search(
        rf"location\s+{re.escape(declaration)}\s*\{{(?P<body>.*?)\n\s*\}}",
        config,
        flags=re.DOTALL,
    )
    assert match is not None, f"missing nginx location {declaration}"
    return match.group("body")


def test_backend_binds_ipv6_all_interfaces_for_railway_dual_stack():
    source = START_SH.read_text(encoding="utf-8")
    command = next(
        line for line in source.splitlines() if line.startswith("uvicorn main:app")
    )
    assert '--host ""' in command
    assert "--host ::" not in command
    assert "--host 0.0.0.0" not in command
    assert "--port 8000" in command


def test_forwarded_header_trust_is_documented_as_private_boundary_only():
    source = START_SH.read_text(encoding="utf-8")
    assert "--proxy-headers --forwarded-allow-ips '*'" in source
    assert "safe only after the backend" in source
    assert "public domain is removed" in source


def test_all_same_origin_backend_surfaces_use_environment_upstream():
    config = NGINX_CONF.read_text(encoding="utf-8")
    assert "resolver ${NGINX_LOCAL_RESOLVERS} valid=10s;" in config
    assert 'set $backend_upstream "${BACKEND_URL}";' in config
    for declaration in ("/api/", "/ws/", "^~ /uploads/"):
        block = _location_block(config, declaration)
        assert "proxy_pass $backend_upstream$request_uri;" in block
        assert "proxy_set_header Host $proxy_host;" in block
        assert "proxy_set_header X-Forwarded-Host $public_original_host;" in block
        assert "proxy_set_header X-Real-IP $public_client_ip;" in block
        assert "proxy_set_header X-Forwarded-For $public_client_ip;" in block
        assert "proxy_set_header X-Forwarded-Proto $public_forwarded_proto;" in block

    ws = _location_block(config, "/ws/")
    assert "proxy_http_version 1.1;" in ws
    assert "proxy_set_header Upgrade $http_upgrade;" in ws
    assert 'proxy_set_header Connection "upgrade";' in ws
    assert "proxy_read_timeout 3600s;" in ws
    assert "proxy_send_timeout 3600s;" in ws


def test_proxy_preserves_edge_scheme_and_public_host_with_local_fallbacks():
    config = NGINX_CONF.read_text(encoding="utf-8")
    assert "map $http_x_forwarded_proto $public_forwarded_proto" in config
    assert "https   https;" in config
    assert "default $scheme;" in config
    assert "map $http_x_forwarded_host $public_original_host" in config
    assert '""      $host;' in config
    assert "map $http_x_forwarded_for $public_client_ip" in config
    assert "(?<railway_client_ip>" in config
    assert "default                           $remote_addr;" in config
    assert "map $http_x_real_ip $public_client_ip" not in config
    assert "$proxy_add_x_forwarded_for" not in config
    assert "$backend_host_header" not in config


def test_frontend_container_keeps_backend_url_environment_driven():
    dockerfile = FRONTEND_DOCKERFILE.read_text(encoding="utf-8")
    assert "COPY nginx.conf /etc/nginx/templates/default.conf.template" in dockerfile
    assert "ENV BACKEND_URL=http://backend:8000" in dockerfile
    assert "ENV NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1" in dockerfile
    assert "railway.internal" not in dockerfile


def test_runbook_requires_private_reference_then_public_domain_removal():
    runbook = DEPLOYMENT.read_text(encoding="utf-8")
    assert 'BACKEND_URL=http://${{backend.RAILWAY_PRIVATE_DOMAIN}}:8000' in runbook
    assert "remove the backend service's Railway public domain" in runbook
    assert "former backend `*.up.railway.app`" in runbook
    assert "**Rollback:**" in runbook
    assert "actual newly-issued" in runbook
    assert "10-second" in runbook
    assert "redeploy **only the backend**" in runbook
    assert "leaving the frontend deployment untouched" in runbook
    assert "resolved upstream as" in runbook
    assert "X-Forwarded-Host" in runbook
