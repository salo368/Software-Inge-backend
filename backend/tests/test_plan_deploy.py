"""Unit tests for scripts/ci/plan-deploy.sh.

Cross-cutting test that shells out to the bash script with the
`PLAN_DEPLOY_TEST_CHANGED_FILES` hook (a newline-separated file list)
so we exercise the actual production code path without needing a real
git repo state.

Cardinal rule under test: ANY infra execution forces a full redeploy
of every service (see the top-of-file comment in plan-deploy.sh).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "ci" / "plan-deploy.sh"


def _run(
    changed_files: str = "",
    manual_block: str | None = None,
) -> dict[str, str]:
    """Runs plan-deploy.sh with the given inputs, returns parsed outputs.

    Uses a temp file as GITHUB_OUTPUT (that's how GitHub Actions passes
    step outputs) and parses the resulting `key=value` lines.
    """
    if not _SCRIPT.exists():
        pytest.skip(f"plan-deploy.sh not found at {_SCRIPT}")
    # Bash may not be on PATH on Windows; try common locations.
    bash = _which_bash()
    if bash is None:
        pytest.skip("bash not available on this system")

    import tempfile

    with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".out") as f:
        github_output_path = f.name

    env = os.environ.copy()
    env["PLAN_DEPLOY_TEST_CHANGED_FILES"] = changed_files
    env["GITHUB_OUTPUT"] = github_output_path
    if manual_block is not None:
        env["MANUAL_BLOCK"] = manual_block
    # Clear GITHUB_EVENT_NAME so the script does not try to interpret this
    # as a push/PR when there is no MANUAL_BLOCK either.
    env.pop("GITHUB_EVENT_NAME", None)
    env.pop("GITHUB_EVENT_BEFORE", None)

    result = subprocess.run(
        [bash, str(_SCRIPT)],
        env=env,
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"plan-deploy.sh exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    outputs: dict[str, str] = {}
    with open(github_output_path) as f:
        for line in f:
            line = line.rstrip("\n")
            if "=" in line:
                k, _, v = line.partition("=")
                outputs[k] = v
    return outputs


def _which_bash() -> str | None:
    """Locate a usable bash binary across OSes."""
    import shutil

    candidates = [
        shutil.which("bash"),
        "/bin/bash",
        "/usr/bin/bash",
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return None


# ---------------------------------------------------------------------------
# Auto-detect diff
# ---------------------------------------------------------------------------
class TestAutoDetect:
    def test_only_outside_backend_changes_deploys_nothing(self):
        """Non-empty diff but every file is outside backend/ -> no-op."""
        out = _run(changed_files="README.md\ndocs/design.md\n.gitignore")
        assert out["services_to_deploy"] == "[]"
        assert out["run_migrations"] == "false"
        assert out["run_assets"] == "false"
        assert out["run_infrastructure"] == "false"
        assert out["transversal"] == "false"
        assert out["total_count"] == "0"

    def test_single_service_change_deploys_only_that_service(self):
        out = _run(
            changed_files="backend/services/auth/src/handlers/login/handler.py"
        )
        assert out["services_to_deploy"] == '["auth"]'
        assert out["transversal"] == "false"
        assert out["run_migrations"] == "false"

    def test_two_service_changes_deduped_and_sorted(self):
        out = _run(
            changed_files=(
                "backend/services/files/src/handlers/get_upload_url/handler.py\n"
                "backend/services/auth/src/handlers/login/handler.py\n"
                "backend/services/auth/src/handlers/logout/handler.py"
            )
        )
        assert out["services_to_deploy"] == '["auth","files"]'
        assert out["transversal"] == "false"

    def test_migration_content_forces_transversal(self):
        """Adding a new SQL file must fan out to ALL services."""
        out = _run(
            changed_files="backend/platform/migrations/sql/20260924_new.sql"
        )
        assert out["run_migrations"] == "true"
        assert out["transversal"] == "true"
        # All services present, alphabetical.
        services = out["services_to_deploy"]
        for svc in ("auth", "banks", "files", "forms", "processes", "signatures"):
            assert f'"{svc}"' in services

    def test_migration_code_forces_transversal(self):
        out = _run(
            changed_files="backend/platform/migrations/src/handlers/apply/handler.py"
        )
        assert out["run_migrations"] == "true"
        assert out["transversal"] == "true"
        assert '"auth"' in out["services_to_deploy"]

    def test_assets_content_forces_transversal(self):
        out = _run(
            changed_files="backend/platform/assets/files/logo.png"
        )
        assert out["run_assets"] == "true"
        assert out["transversal"] == "true"
        assert '"auth"' in out["services_to_deploy"]

    def test_backend_global_change_forces_transversal_but_no_infra(self):
        out = _run(changed_files="backend/libs/utils/lambda_invoke.py")
        assert out["transversal"] == "true"
        assert out["run_migrations"] == "false"
        assert out["run_assets"] == "false"
        assert '"auth"' in out["services_to_deploy"]

    def test_outside_backend_is_ignored(self):
        out = _run(changed_files="README.md\ndocs/foo.md")
        assert out["services_to_deploy"] == "[]"
        assert out["transversal"] == "false"
        assert out["run_migrations"] == "false"

    def test_mixed_service_and_migration_still_transversal(self):
        """A migration + a service change: migration wins, all deploy."""
        out = _run(
            changed_files=(
                "backend/services/auth/src/handlers/login/handler.py\n"
                "backend/platform/migrations/sql/20260924_x.sql"
            )
        )
        assert out["run_migrations"] == "true"
        assert out["transversal"] == "true"
        assert '"signatures"' in out["services_to_deploy"]


# ---------------------------------------------------------------------------
# Manual overrides
# ---------------------------------------------------------------------------
class TestManualOverride:
    def test_all_deploys_everything(self):
        out = _run(manual_block="__all__")
        assert out["run_migrations"] == "true"
        assert out["run_assets"] == "true"
        assert out["transversal"] == "true"
        assert '"auth"' in out["services_to_deploy"]

    def test_manual_service_deploys_only_that_service(self):
        out = _run(manual_block="auth")
        assert out["services_to_deploy"] == '["auth"]'
        assert out["transversal"] == "false"
        assert out["run_migrations"] == "false"

    def test_manual_infra_migrations_forces_full_service_redeploy(self):
        """This is the bug the user caught: `block=migrations` used to
        run only migrations without redeploying services, leaving the
        fleet inconsistent with the new schema."""
        out = _run(manual_block="migrations")
        assert out["run_migrations"] == "true"
        assert out["transversal"] == "true"
        for svc in ("auth", "banks", "files", "forms", "processes", "signatures"):
            assert f'"{svc}"' in out["services_to_deploy"]

    def test_manual_infra_assets_forces_full_service_redeploy(self):
        out = _run(manual_block="assets")
        assert out["run_assets"] == "true"
        assert out["transversal"] == "true"
        assert '"auth"' in out["services_to_deploy"]

    def test_manual_unknown_block_exits_nonzero(self):
        """Explicit rejection instead of a silent no-op."""
        bash = _which_bash()
        if bash is None:
            pytest.skip("bash not available")
        env = os.environ.copy()
        env["MANUAL_BLOCK"] = "does-not-exist"
        env["GITHUB_OUTPUT"] = "/tmp/plan-deploy-nowhere"  # never opened
        env.pop("GITHUB_EVENT_NAME", None)
        env.pop("PLAN_DEPLOY_TEST_CHANGED_FILES", None)
        r = subprocess.run(
            [bash, str(_SCRIPT)],
            env=env,
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert r.returncode != 0
        assert "MANUAL_BLOCK" in r.stderr
