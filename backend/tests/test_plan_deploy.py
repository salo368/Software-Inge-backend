"""Unit tests for scripts/ci/plan-deploy.sh.

Cross-cutting tests split in two flavors:

  1. `PLAN_DEPLOY_TEST_CHANGED_FILES` hook -- injects a newline-separated
     file list to skip git diff altogether. Fast, covers the
     classification / fan-out rules.

  2. Real ephemeral git repos -- for tests that exercise the git-based
     branches of the script (push with LAST_SUCCESSFUL_DEPLOY_SHA,
     GITHUB_EVENT_BEFORE fallback, etc). Slower but the only way to
     verify the actual `git diff` command inside the script.

Cardinal rule under test: ANY infra execution forces a full redeploy
of every service (see the top-of-file comment in plan-deploy.sh).
"""
from __future__ import annotations

import os
import subprocess
import textwrap
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


# ---------------------------------------------------------------------------
# Push-event branch: real ephemeral git repos.
#
# These exercise the branch of the script that computes CHANGED_FILES via
# `git diff BASE..HEAD` and, critically, the `LAST_SUCCESSFUL_DEPLOY_SHA`
# fallback that saves us when a prior pipeline failed before Infrastructure
# ran (the exact bug that caused the missed migration in the ORM change).
# ---------------------------------------------------------------------------
def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return r.stdout.strip()


def _init_repo(tmp: Path) -> None:
    """Init a repo with the same directory layout plan-deploy scans:
       backend/services/{auth,banks,files,forms,processes,signatures}/
       backend/platform/{migrations,assets}/
    """
    _git(tmp, "init", "-q", "-b", "main")
    _git(tmp, "config", "user.email", "test@test.local")
    _git(tmp, "config", "user.name", "test")
    for svc in ("auth", "banks", "files", "forms", "processes", "signatures"):
        d = tmp / "backend" / "services" / svc
        d.mkdir(parents=True)
        (d / "handler.py").write_text("# placeholder\n")
    (tmp / "backend" / "platform" / "migrations" / "sql").mkdir(parents=True)
    (tmp / "backend" / "platform" / "assets" / "files").mkdir(parents=True)
    _git(tmp, "add", "-A")
    _git(tmp, "commit", "-q", "-m", "initial")


def _run_git(
    cwd: Path,
    *,
    before: str,
    head: str = "HEAD",
    last_successful: str | None = None,
) -> dict[str, str]:
    """Runs plan-deploy.sh from `cwd` as if it were a `push` event.

    `before` mimics GITHUB_EVENT_BEFORE (the parent-of-push commit).
    `last_successful` mimics LAST_SUCCESSFUL_DEPLOY_SHA emitted by the
    Plan job's gh-run-list step.
    """
    bash = _which_bash()
    if bash is None:
        pytest.skip("bash not available")

    import tempfile

    with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".out") as f:
        github_output_path = f.name

    env = os.environ.copy()
    env["GITHUB_OUTPUT"] = github_output_path
    env["GITHUB_EVENT_NAME"] = "push"
    env["GITHUB_EVENT_BEFORE"] = before
    if last_successful is not None:
        env["LAST_SUCCESSFUL_DEPLOY_SHA"] = last_successful
    else:
        env.pop("LAST_SUCCESSFUL_DEPLOY_SHA", None)
    env.pop("PLAN_DEPLOY_TEST_CHANGED_FILES", None)
    env.pop("MANUAL_BLOCK", None)

    # Checkout `head` if not already there.
    if head != "HEAD":
        _git(cwd, "checkout", "-q", head)

    r = subprocess.run(
        [bash, str(_SCRIPT)],
        env=env,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, (
        f"exit {r.returncode}\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"
    )

    outputs: dict[str, str] = {}
    with open(github_output_path) as f:
        for line in f:
            line = line.rstrip("\n")
            if "=" in line:
                k, _, v = line.partition("=")
                outputs[k] = v
    outputs["_stderr"] = r.stderr
    return outputs


class TestPushBranchWithGit:
    """Real-git-repo tests for the push branch of plan-deploy.sh."""

    def test_diff_uses_github_event_before_when_no_last_successful(
        self, tmp_path
    ):
        _init_repo(tmp_path)
        c0 = _git(tmp_path, "rev-parse", "HEAD")
        # single service change on top of c0
        (tmp_path / "backend" / "services" / "auth" / "handler.py").write_text(
            "# touched\n"
        )
        _git(tmp_path, "commit", "-q", "-am", "touch auth")
        out = _run_git(tmp_path, before=c0, last_successful=None)
        assert out["services_to_deploy"] == '["auth"]'
        assert out["transversal"] == "false"

    def test_missed_migration_replay_via_last_successful(self, tmp_path):
        """The regression case that motivated the fix.

        Timeline:
          c0 -- initial (last SUCCESSFUL deploy)
          c1 -- adds a migration; its pipeline dies at Validate; migration
                is NEVER applied to the DB
          c2 -- unrelated cosmetic change

        A dumb diff (c1..c2) does not see the migration file (it already
        lives in c1's tree), so plan-deploy would say run_migrations=false
        and the schema stays stale.

        The correct diff (c0..c2) still contains the migration, so
        run_migrations=true and Infrastructure catches up.
        """
        _init_repo(tmp_path)
        c0 = _git(tmp_path, "rev-parse", "HEAD")

        # c1: add a migration (pipeline for this hypothetically failed
        # before Infrastructure).
        (
            tmp_path
            / "backend"
            / "platform"
            / "migrations"
            / "sql"
            / "20260924_dummy.sql"
        ).write_text("-- noop\n")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", "add migration (pipeline failed)")
        c1 = _git(tmp_path, "rev-parse", "HEAD")

        # c2: unrelated change.
        (tmp_path / "README.md").write_text("hello\n")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", "unrelated readme")

        # Simulate what the OLD script did (GITHUB_EVENT_BEFORE=c1, no
        # last-successful-deploy anchor) -- migration would be MISSED.
        broken = _run_git(tmp_path, before=c1, last_successful=None)
        assert broken["run_migrations"] == "false", (
            "sanity: without the anchor the migration is invisible; "
            "this is exactly the bug the fix addresses"
        )

        # NEW behaviour: last_successful=c0 makes the diff c0..HEAD which
        # still contains the SQL file. Infrastructure re-runs.
        fixed = _run_git(tmp_path, before=c1, last_successful=c0)
        assert fixed["run_migrations"] == "true"
        assert fixed["transversal"] == "true"
        # And full fan-out per cardinal rule.
        for svc in (
            "auth",
            "banks",
            "files",
            "forms",
            "processes",
            "signatures",
        ):
            assert f'"{svc}"' in fixed["services_to_deploy"]

    def test_last_successful_sha_unreachable_falls_back_to_before(
        self, tmp_path
    ):
        """If gh returns a SHA that isn't in the local repo (repo history
        rewritten, force-push, whatever), the script must not crash --
        it should log a warning and fall back to GITHUB_EVENT_BEFORE."""
        _init_repo(tmp_path)
        c0 = _git(tmp_path, "rev-parse", "HEAD")
        (tmp_path / "backend" / "services" / "auth" / "handler.py").write_text(
            "# touched\n"
        )
        _git(tmp_path, "commit", "-q", "-am", "touch auth")

        out = _run_git(
            tmp_path,
            before=c0,
            last_successful="0" * 40,  # syntactically-valid but unknown
        )
        assert "not present locally" in out["_stderr"]
        # Falls back to before=c0, still picks up the auth change.
        assert out["services_to_deploy"] == '["auth"]'
