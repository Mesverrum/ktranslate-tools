"""
FastAPI admin sidecar for KtransToGrafana's multi-credential-group layout.

Thin vertical slice — three endpoints to exercise the full round-trip:
read → edit → regenerate → SIGHUP. The rest of the planned endpoint
surface (devices, discovery, /test, /status) goes in follow-ups once
the round-trip is verified end-to-end against a live stack.
"""
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .env_parser import parse_env_file, write_env_file
from .operations import OperationError, regenerate_groups, sighup_poller


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("ktranslate-admin")

WORKSPACE = Path(os.environ.get("WORKSPACE", "/workspace"))
GROUPS_DIR = WORKSPACE / "groups"

app = FastAPI(
    title="ktranslate-tools admin",
    description="Point-and-click admin for ktranslate multi-credential-group deployments.",
    version="0.1.0",
)


class GroupSummary(BaseModel):
    name: str
    snmp_version: str
    poll_interval_sec: int
    metalisten_port: int
    trap_port: int


class GroupDetail(GroupSummary):
    snmp_v3_user: str | None = None
    snmp_v2_community: str | None = None
    trap_community: str = ""
    targets: list[str] = Field(default_factory=list)
    discovery_threads: int = 2


class GroupUpdate(BaseModel):
    """Every field optional — PUT with just the keys you want to change."""
    poll_interval_sec: int | None = Field(default=None, ge=10, le=86400)
    metalisten_port: int | None = Field(default=None, ge=1, le=65535)
    trap_port: int | None = Field(default=None, ge=1, le=65535)
    discovery_threads: int | None = Field(default=None, ge=1, le=64)
    snmp_v3_user: str | None = None
    snmp_v2_community: str | None = None
    trap_community: str | None = None
    targets: list[str] | None = None


# ----- helpers -------------------------------------------------------------

def _group_path(name: str) -> Path:
    path = GROUPS_DIR / f"{name}.env"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"group not found: {name}")
    return path


def _detail_from_env(name: str, data: dict[str, str]) -> GroupDetail:
    return GroupDetail(
        name=data.get("GROUP", name),
        snmp_version=data.get("SNMP_VERSION", "v2c"),
        poll_interval_sec=int(data.get("POLL_INTERVAL_SEC", "60")),
        metalisten_port=int(data.get("METALISTEN_PORT", "0")),
        trap_port=int(data.get("TRAP_PORT", "0")),
        snmp_v3_user=data.get("SNMP_V3_USER") or None,
        snmp_v2_community=data.get("SNMP_V2_COMMUNITY") or None,
        trap_community=data.get("TRAP_COMMUNITY", ""),
        targets=[t.strip() for t in data.get("TARGETS", "").split(",") if t.strip()],
        discovery_threads=int(data.get("DISCOVERY_THREADS", "2")),
    )


# ----- endpoints -----------------------------------------------------------

@app.get("/api/groups", response_model=list[GroupSummary])
def list_groups() -> list[GroupSummary]:
    if not GROUPS_DIR.exists():
        return []
    out: list[GroupSummary] = []
    for env_path in sorted(GROUPS_DIR.glob("*.env")):
        data = parse_env_file(env_path)
        out.append(GroupSummary(
            name=data.get("GROUP", env_path.stem),
            snmp_version=data.get("SNMP_VERSION", "v2c"),
            poll_interval_sec=int(data.get("POLL_INTERVAL_SEC", "60")),
            metalisten_port=int(data.get("METALISTEN_PORT", "0")),
            trap_port=int(data.get("TRAP_PORT", "0")),
        ))
    return out


@app.get("/api/groups/{name}", response_model=GroupDetail)
def get_group(name: str) -> GroupDetail:
    data = parse_env_file(_group_path(name))
    return _detail_from_env(name, data)


@app.put("/api/groups/{name}", response_model=GroupDetail)
def update_group(name: str, update: GroupUpdate) -> GroupDetail:
    path = _group_path(name)

    # Translate the model into env-var key/value updates. Order doesn't
    # matter for write — env_parser preserves the file's existing layout.
    changes: dict[str, str] = {}
    if update.poll_interval_sec is not None:
        changes["POLL_INTERVAL_SEC"] = str(update.poll_interval_sec)
    if update.metalisten_port is not None:
        changes["METALISTEN_PORT"] = str(update.metalisten_port)
    if update.trap_port is not None:
        changes["TRAP_PORT"] = str(update.trap_port)
    if update.discovery_threads is not None:
        changes["DISCOVERY_THREADS"] = str(update.discovery_threads)
    if update.snmp_v3_user is not None:
        changes["SNMP_V3_USER"] = update.snmp_v3_user
    if update.snmp_v2_community is not None:
        changes["SNMP_V2_COMMUNITY"] = update.snmp_v2_community
    if update.trap_community is not None:
        changes["TRAP_COMMUNITY"] = update.trap_community
    if update.targets is not None:
        changes["TARGETS"] = ",".join(update.targets)

    if changes:
        log.info("updating group %s: %s", name, changes)
        write_env_file(path, changes)
        try:
            regenerate_groups(WORKSPACE)
            sighup_poller(WORKSPACE, name)
        except OperationError as exc:
            log.error("operation failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    else:
        log.info("update for group %s contained no changes", name)

    return _detail_from_env(name, parse_env_file(path))


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
