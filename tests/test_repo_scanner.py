from pathlib import Path

from repodocmake.analyzer import scan_repository


def _make_repo(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "sample-pkg"\nversion = "1.2.3"\ndependencies = ["click"]\n',
        encoding="utf-8",
    )
    (tmp_path / "sample.py").write_text(
        'def greet(name):\n    """Say hi."""\n    return f"hi {name}"\n\nclass Greeter:\n    pass\n',
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# sample\n", encoding="utf-8")
    return tmp_path


def test_scan_extracts_package_metadata(tmp_path):
    profile = scan_repository(str(_make_repo(tmp_path)))
    assert profile.package_name == "sample-pkg"
    assert profile.version == "1.2.3"
    assert profile.primary_language == "Python"
    assert "click" in profile.dependencies


def test_scan_detects_existing_docs(tmp_path):
    profile = scan_repository(str(_make_repo(tmp_path)))
    assert "README" in profile.existing_docs
    assert "CONTRIBUTING" not in profile.existing_docs


def test_scan_profiles_python_api(tmp_path):
    profile = scan_repository(str(_make_repo(tmp_path)))
    names = {f.name for m in profile.modules for f in m.functions}
    classes = {c for m in profile.modules for c in m.classes}
    assert "greet" in names
    assert "Greeter" in classes


def test_scan_falls_back_to_requirements_txt(tmp_path):
    # No pyproject.toml — a requirements.txt-only project (e.g. FastAPI app).
    (tmp_path / "main.py").write_text("def app():\n    return 1\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text(
        "# core\n"
        "fastapi==0.110.0\n"
        "uvicorn[standard]>=0.29\n"
        "bcrypt==4.1.2  # auth\n"
        "\n"
        "-r dev-requirements.txt\n"          # option line — skipped
        "boto3==1.42.9 ; python_version >= '3.10'\n",  # env marker stripped
        encoding="utf-8",
    )
    profile = scan_repository(str(tmp_path))
    assert profile.package_name is None          # no manifest declares a name
    assert "fastapi==0.110.0" in profile.dependencies
    assert "uvicorn[standard]>=0.29" in profile.dependencies
    assert "bcrypt==4.1.2" in profile.dependencies
    assert "boto3==1.42.9" in profile.dependencies
    assert not any(d.startswith("-r") for d in profile.dependencies)
    assert "requirements.txt" in profile.manifests


def test_pyproject_deps_take_precedence_over_requirements(tmp_path):
    repo = _make_repo(tmp_path)  # has pyproject with dependencies = ["click"]
    (repo / "requirements.txt").write_text("requests==2.0\n", encoding="utf-8")
    profile = scan_repository(str(repo))
    assert "click" in profile.dependencies
    assert "requests==2.0" not in profile.dependencies   # pyproject wins
    assert {"pyproject.toml", "requirements.txt"} <= set(profile.manifests)


def test_scan_extracts_metadata_from_setup_py(tmp_path):
    # No pyproject — a classic setuptools project with setup.py.
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "setup.py").write_text(
        "from setuptools import setup\n"
        "setup(\n"
        '    name="my-tool",\n'
        '    version="2.1.0",\n'
        '    install_requires=["click>=8", "rich"],\n'
        ")\n",
        encoding="utf-8",
    )
    profile = scan_repository(str(tmp_path))
    assert profile.package_name == "my-tool"
    assert profile.version == "2.1.0"
    assert "click>=8" in profile.dependencies
    assert "setup.py" in profile.manifests


def test_scan_extracts_metadata_from_setup_cfg(tmp_path):
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "setup.cfg").write_text(
        "[metadata]\n"
        "name = cfg-pkg\n"
        "version = 0.5.0\n"
        "[options]\n"
        "install_requires =\n"
        "    click\n"
        "    requests>=2\n",
        encoding="utf-8",
    )
    profile = scan_repository(str(tmp_path))
    assert profile.package_name == "cfg-pkg"
    assert profile.version == "0.5.0"
    assert "requests>=2" in profile.dependencies


def test_setup_py_is_not_executed(tmp_path):
    # A module-level raise would crash scanning if setup.py were executed.
    # AST parsing still finds the setup() call, proving we read, not run, it.
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "setup.py").write_text(
        "from setuptools import setup\n"
        "raise RuntimeError('setup.py was executed!')\n"
        'setup(name="boom")\n',
        encoding="utf-8",
    )
    profile = scan_repository(str(tmp_path))  # must not raise
    assert profile.package_name == "boom"


def test_pyproject_name_wins_over_setup_py(tmp_path):
    repo = _make_repo(tmp_path)  # pyproject name = sample-pkg
    (repo / "setup.py").write_text(
        'from setuptools import setup\nsetup(name="other-name")\n', encoding="utf-8"
    )
    profile = scan_repository(str(repo))
    assert profile.package_name == "sample-pkg"


def test_scan_reads_package_json_for_js_project(tmp_path):
    (tmp_path / "index.ts").write_text("export const x = 1\n", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        '{"name": "web-app", "version": "0.3.0", '
        '"dependencies": {"next": "^15", "react": "^19"}, '
        '"devDependencies": {"eslint": "^9"}}',
        encoding="utf-8",
    )
    profile = scan_repository(str(tmp_path))
    assert profile.package_name == "web-app"
    assert profile.version == "0.3.0"
    assert "next" in profile.dependencies and "react" in profile.dependencies
    assert "eslint" not in profile.dependencies      # devDependencies excluded
    assert "package.json" in profile.manifests


def test_python_manifest_not_overridden_by_frontend_package_json(tmp_path):
    # A Python service that ships a frontend package.json must keep its own
    # identity (the package.json name must NOT become the project name).
    (tmp_path / "main.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("fastapi==0.110\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name": "frontend"}', encoding="utf-8")
    profile = scan_repository(str(tmp_path))
    assert profile.package_name is None              # not "frontend"
    assert "fastapi==0.110" in profile.dependencies
