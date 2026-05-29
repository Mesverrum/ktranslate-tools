"""
Shell out to the existing KtransToGrafana scripts.

We don't reimplement the generator or the discovery flow in Python —
they live in scripts/generate-groups.sh and scripts/run-discovery.sh
inside the workspace, and this sidecar just calls them. That keeps a
single source of truth for the file format and the SIGHUP logic.
"""
import subprocess
from pathlib import Path


class OperationError(RuntimeError):
    """A shelled-out script failed; the message contains its stderr."""


def regenerate_groups(workspace: Path) -> None:
    """Run scripts/generate-groups.sh to re-render configs + compose snippet."""
    script = workspace / "scripts" / "generate-groups.sh"
    if not script.exists():
        raise OperationError(f"missing script: {script}")
    result = subprocess.run(
        ["bash", str(script)],
        cwd=workspace,
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


def _compose_args(workspace: Path) -> list[str]:
    return [
        "docker", "compose",
        "-f", str(workspace / "compose-base.yaml"),
        "-f", str(workspace / "compose-groups.generated.yaml"),
    ]


def sighup_poller(workspace: Path, group: str) -> bool:
    """Send SIGHUP to the matching poller container so it re-reads its config.

    Returns True if a signal was sent, False if the container wasn't running
    (e.g. first-time setup before `docker compose up`). Failing to signal a
    stopped container is not an error — the new config will take effect when
    it starts.
    """
    service = f"ktranslate_snmp_{group}"
    base = _compose_args(workspace)

    check = subprocess.run(
        base + ["ps", "--status", "running", "--services"],
        capture_output=True, text=True, check=False,
    )
    if service not in check.stdout.splitlines():
        return False

    result = subprocess.run(
        base + ["kill", "-s", "HUP", service],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise OperationError(
            f"docker compose kill failed (rc={result.returncode}):\n"
            f"stderr:\n{result.stderr}"
        )
    return True
