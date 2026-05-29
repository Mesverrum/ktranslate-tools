"""
Shell out to the existing KtransToGrafana scripts.

We don't reimplement the generator or the discovery flow in Python —
they live in scripts/generate-groups.sh and scripts/run-discovery.sh
inside the workspace, and this sidecar just calls them. That keeps a
single source of truth for the file format and the reload logic.
"""
import logging
import os
import subprocess
from pathlib import Path


log = logging.getLogger("ktranslate-admin.ops")


class OperationError(RuntimeError):
    """A shelled-out script failed; the message contains its stderr."""


# --- compose project resolution --------------------------------------------

def _detect_project_name() -> str | None:
    """Find the compose project this stack is running under.

    docker compose derives the project name from the compose file's parent
    directory by default. When the sidecar runs `docker compose ...` from
    inside its own container, the file lives at /workspace/* and compose
    would call the project "workspace" — but the user's stack was started
    from a different cwd and so registered under a different name.
    Detect the actual project by looking at any container running under
    docker compose; they all carry com.docker.compose.project as a label.
    """
    result = subprocess.run(
        ["docker", "ps",
         "--filter", "label=com.docker.compose.project",
         "--format", '{{index .Labels "com.docker.compose.project"}}'],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        log.warning("docker ps failed during project detection: %s", result.stderr.strip())
        return None
    projects = {p.strip() for p in result.stdout.splitlines() if p.strip()}
    if len(projects) == 1:
        return next(iter(projects))
    if len(projects) > 1:
        log.warning(
            "multiple compose projects running (%s); set COMPOSE_PROJECT_NAME to disambiguate",
            ", ".join(sorted(projects)),
        )
    return None


def _compose_args(workspace: Path) -> list[str]:
    args = ["docker", "compose"]
    project = os.environ.get("COMPOSE_PROJECT_NAME") or _detect_project_name()
    if project:
        args += ["-p", project]
    args += [
        "-f", str(workspace / "compose-base.yaml"),
        "-f", str(workspace / "compose-groups.generated.yaml"),
    ]
    return args


# --- operations -------------------------------------------------------------

def regenerate_groups(workspace: Path) -> None:
    """Run scripts/generate-groups.sh to re-render configs + compose snippet.

    If KTRANS_HOST_PATH is set in the sidecar's environment, it's forwarded
    to the generator as REPO_PATH so the bind-mount sources baked into
    compose-groups.generated.yaml resolve correctly on the docker host.
    Without this, the generator's self-derived REPO_ROOT picks up the
    sidecar's /workspace mount path, which doesn't exist on the host —
    docker then auto-creates empty directories at those paths and pollers
    crash with 'is a directory' when mounting their snmp.yaml.
    """
    script = workspace / "scripts" / "generate-groups.sh"
    if not script.exists():
        raise OperationError(f"missing script: {script}")
    log.info("running %s", script)

    env = os.environ.copy()
    host_path = os.environ.get("KTRANS_HOST_PATH")
    if host_path:
        env["REPO_PATH"] = host_path
        log.info("overriding REPO_PATH=%s (KTRANS_HOST_PATH)", host_path)
    else:
        log.info(
            "KTRANS_HOST_PATH not set; generator will derive REPO_PATH from its own "
            "filesystem location. This is fine on host runs but will break compose "
            "bind-mounts when the sidecar regenerates."
        )

    result = subprocess.run(
        ["bash", str(script)],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise OperationError(
            f"generate-groups.sh failed (rc={result.returncode}):\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    # The script's own progress lines are useful — surface them.
    for line in result.stdout.splitlines():
        if line.strip():
            log.info("generate: %s", line)


def reload_poller(workspace: Path, group: str) -> bool:
    """Send SIGUSR2 to the matching poller container so it re-reads its config.

    ktranslate's SNMP input handles SIGUSR2 to restart its main loop with the
    current on-disk config (pkg/inputs/snmp/snmp.go). SIGHUP has no handler
    and falls through to the default disposition, which terminates the
    container — so don't send that one.

    Returns True if a signal was sent, False if the container wasn't running
    (e.g. first-time setup before `docker compose up`). Failing to signal a
    stopped container is not an error — the new config will take effect when
    it starts.
    """
    service = f"ktranslate_snmp_{group}"
    base = _compose_args(workspace)
    log.info("checking poller status: service=%s args=%s", service, " ".join(base))

    check = subprocess.run(
        base + ["ps", "--status", "running", "--services"],
        capture_output=True, text=True, check=False,
    )
    running = [s.strip() for s in check.stdout.splitlines() if s.strip()]
    log.info("running services: %s", running or "(none)")

    if service not in running:
        log.warning(
            "service %s not in running set; skipping reload signal. "
            "Config changes will take effect when the poller next starts.",
            service,
        )
        return False

    result = subprocess.run(
        base + ["kill", "-s", "USR2", service],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise OperationError(
            f"docker compose kill failed (rc={result.returncode}):\n"
            f"stderr:\n{result.stderr}"
        )
    log.info("sent SIGUSR2 to %s", service)
    return True
