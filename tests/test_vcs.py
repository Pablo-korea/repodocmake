import subprocess
from pathlib import Path

from docforgeai import vcs


def _git(args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(["init"], path)
    _git(["config", "user.email", "test@example.com"], path)
    _git(["config", "user.name", "Test"], path)
    (path / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(["add", "seed.txt"], path)
    _git(["commit", "-m", "init"], path)
    return path


def test_commit_mode_commits_generated_docs(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    (repo / "README.md").write_text("# hello\n", encoding="utf-8")

    committed = vcs.commit_mode(str(repo), ["README.md"])

    assert committed is True
    assert "README.md" in _git(["ls-files"], repo).splitlines()
    assert "[docforgeai]" in _git(["log", "-1", "--pretty=%s"], repo)


def test_commit_mode_is_noop_when_nothing_changed(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    (repo / "README.md").write_text("# hello\n", encoding="utf-8")
    vcs.commit_mode(str(repo), ["README.md"])

    # Same content again — nothing staged, so no second commit.
    assert vcs.commit_mode(str(repo), ["README.md"]) is False


def test_pr_mode_pushes_branch_and_skips_pr_without_token(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)

    remote = tmp_path / "origin.git"
    remote.mkdir()
    _git(["init", "--bare"], remote)

    repo = _init_repo(tmp_path / "work")
    _git(["remote", "add", "origin", str(remote)], repo)
    (repo / "CONTRIBUTING.md").write_text("# contributing\n", encoding="utf-8")

    url = vcs.pr_mode(str(repo), ["CONTRIBUTING.md"], branch="docforgeai/update-docs")

    assert url is None                                   # no token -> PR skipped
    remote_branches = _git(["ls-remote", "--heads", "origin"], repo)
    assert "docforgeai/update-docs" in remote_branches     # branch was pushed


def test_pr_mode_returns_none_when_no_changes(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    repo = _init_repo(tmp_path / "work")
    # File already committed identically -> branch has nothing new to commit.
    (repo / "README.md").write_text("# hello\n", encoding="utf-8")
    vcs.commit_mode(str(repo), ["README.md"])

    assert vcs.pr_mode(str(repo), ["README.md"]) is None
