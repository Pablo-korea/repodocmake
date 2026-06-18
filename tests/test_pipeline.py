from pathlib import Path

import docforgeai.pipeline as pipeline
from docforgeai.config import Config
from docforgeai.models import DocKind, GeneratedDoc, RepoProfile
from docforgeai.pipeline import _consistency_issues, missing_docs, run


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (tmp_path / "demo.py").write_text("def f(x):\n    return x\n", encoding="utf-8")
    return tmp_path


def test_dry_run_generates_without_network(tmp_path):
    config = Config(
        target=str(_repo(tmp_path)),
        files=[DocKind.README, DocKind.LICENSE],
        dry_run=True,
    )
    docs = run(config)
    by_kind = {d.kind: d for d in docs}
    assert by_kind[DocKind.README].content  # mock LLM produced something
    assert "Apache License" in by_kind[DocKind.LICENSE].content


def test_existing_doc_is_skipped(tmp_path):
    repo = _repo(tmp_path)
    (repo / "README.md").write_text("# demo\n", encoding="utf-8")
    config = Config(target=str(repo), files=[DocKind.README], dry_run=True)
    docs = run(config)
    assert docs[0].skipped
    assert "already exists" in docs[0].reason


def test_license_only_supports_known_spdx(tmp_path):
    config = Config(target=str(_repo(tmp_path)), files=[DocKind.LICENSE], license="MIT", dry_run=True)
    docs = run(config)
    assert "MIT License" in docs[0].content


def test_license_is_full_text_not_truncated(tmp_path):
    config = Config(target=str(_repo(tmp_path)), files=[DocKind.LICENSE], license="MIT", dry_run=True)
    content = run(config)[0].content
    # The disclaimer is the tail of the real MIT text; truncation would drop it.
    assert "WITHOUT WARRANTY OF ANY KIND" in content
    assert "..." not in content


def test_license_holder_is_not_the_package_name(tmp_path):
    # package_name is "demo"; the copyright holder must not be the bare pkg name.
    config = Config(target=str(_repo(tmp_path)), files=[DocKind.LICENSE], license="MIT", dry_run=True)
    content = run(config)[0].content
    assert "Copyright (c) 2026 The demo authors" in content
    assert "Copyright (c) 2026 demo\n" not in content


def test_license_honors_explicit_holder(tmp_path):
    config = Config(target=str(_repo(tmp_path)), files=[DocKind.LICENSE],
                    license="Apache-2.0", holder="Acme Corp", dry_run=True)
    content = run(config)[0].content
    assert "Copyright 2026 Acme Corp" in content
    assert "END OF TERMS AND CONDITIONS" in content  # full Apache body present


# --- consistency gate ---------------------------------------------------------

def _profile() -> RepoProfile:
    return RepoProfile(name="demo", root=".", package_name="demo",
                       dependencies=["pydantic>=2.6"])


def test_gate_flags_missing_package_name_in_readme():
    doc = GeneratedDoc(kind=DocKind.README, filename="README.md",
                       content="# A project\n\nNo package mentioned here.\n")
    assert any("package name 'demo'" in i for i in _consistency_issues(doc, _profile()))


def test_gate_flags_hallucinated_pip_install():
    doc = GeneratedDoc(kind=DocKind.README, filename="README.md",
                       content="# demo\n\n    pip install totally-made-up\n")
    issues = _consistency_issues(doc, _profile())
    assert any("totally-made-up" in i for i in issues)


def test_gate_accepts_real_package_and_dependency():
    doc = GeneratedDoc(
        kind=DocKind.README, filename="README.md",
        # real package (underscore variant) + a real dependency + `pip install .`
        content="# demo\n\n    pip install demo\n    pip install pydantic\n    pip install -e .\n",
    )
    assert _consistency_issues(doc, _profile()) == []


# --- self-correcting loop -----------------------------------------------------

class _FakeClient:
    """Returns a bad draft until it sees the correction feedback marker."""

    def __init__(self, always_bad: bool = False):
        self.always_bad = always_bad
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        corrective = "previous draft FAILED" in user
        if self.always_bad or not corrective:
            return "# project\n\nno package here\n"      # fails the gate
        return "# demo\n\n    pip install demo\n"        # passes the gate


def test_loop_self_corrects_and_clears_issue(tmp_path, monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(pipeline, "get_client", lambda *a, **k: fake)
    config = Config(target=str(_repo(tmp_path)), files=[DocKind.README],
                    correction_rounds=2)
    doc = run(config)[0]

    assert fake.calls == 2                       # one initial + one correction
    assert "demo" in doc.content
    assert "passed after 1 correction" in (doc.reason or "")


def test_loop_warns_after_exhausting_rounds(tmp_path, monkeypatch):
    fake = _FakeClient(always_bad=True)
    monkeypatch.setattr(pipeline, "get_client", lambda *a, **k: fake)
    config = Config(target=str(_repo(tmp_path)), files=[DocKind.README],
                    correction_rounds=2)
    doc = run(config)[0]

    assert fake.calls == 3                        # initial + 2 correction rounds
    assert "consistency warnings after 2" in (doc.reason or "")


# --- check mode (missing_docs) ------------------------------------------------

def test_missing_docs_reports_only_generatable_absent_docs(tmp_path):
    repo = _repo(tmp_path)
    (repo / "README.md").write_text("# demo\n", encoding="utf-8")  # exists
    config = Config(
        target=str(repo),
        # SECURITY has no generator and must NOT count as drift.
        files=[DocKind.README, DocKind.CONTRIBUTING, DocKind.SECURITY],
    )
    missing = missing_docs(config)
    assert missing == ["CONTRIBUTING"]            # README present, SECURITY excluded


def test_missing_docs_writes_nothing(tmp_path):
    repo = _repo(tmp_path)
    before = {p.name for p in repo.iterdir()}
    missing_docs(Config(target=str(repo), files=[DocKind.README, DocKind.LICENSE]))
    after = {p.name for p in repo.iterdir()}
    assert before == after                        # check mode is non-destructive


# --- language / bilingual output ----------------------------------------------

class _CapturingClient:
    """Records the user prompt it was asked to complete."""

    def __init__(self):
        self.user = ""

    def complete(self, system: str, user: str) -> str:
        self.user = user
        return "# demo\n\npip install demo\n"


def test_bilingual_directive_reaches_the_prompt(tmp_path, monkeypatch):
    cap = _CapturingClient()
    monkeypatch.setattr(pipeline, "get_client", lambda *a, **k: cap)
    config = Config(target=str(_repo(tmp_path)), files=[DocKind.README], language="ko+en")
    run(config)
    assert "bilingually" in cap.user and "Korean" in cap.user


def test_default_language_adds_no_directive(tmp_path, monkeypatch):
    cap = _CapturingClient()
    monkeypatch.setattr(pipeline, "get_client", lambda *a, **k: cap)
    run(Config(target=str(_repo(tmp_path)), files=[DocKind.README]))  # default en
    assert "bilingually" not in cap.user and "Korean" not in cap.user
