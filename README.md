# RepoDocMake

> AI-powered open-source documentation generator — as a GitHub Action and a CLI.

RepoDocMake scans a repository, analyzes its code, and generates OSS docs:
`README`, `LICENSE`, `CONTRIBUTING`, and `DEVELOPER_GUIDE`.

## Installation

```bash
pip install repodocmake
```

## CLI usage

```bash
# Generate docs in place into the current repo (writes the files here)
repodocmake generate . --files README,CONTRIBUTING --license Apache-2.0

# Run it on a locally cloned repo and commit the docs there in one step
repodocmake generate /path/to/cloned-repo --commit

# Offline preview into a separate dir, no API key needed (uses a mock LLM)
repodocmake generate . --dry-run --out ./generated-docs
```

The CLI reads `ANTHROPIC_API_KEY` (or the relevant provider key) from a local
`.env` automatically. Without `--out`, docs are written in place into the
target; with `--out`, they go to that preview directory instead.

### Options

| Option        | Description                                                        |
|---------------|--------------------------------------------------------------------|
| `--files`     | Comma-separated doc kinds: `README,LICENSE,CONTRIBUTING,DEVELOPER_GUIDE`. |
| `--license`   | SPDX license identifier (`MIT`, `Apache-2.0`, `BSD-3-Clause`).     |
| `--language`  | Doc language: `en` \| `ko` \| `ko+en` (bilingual).                 |
| `--llm-provider` | `anthropic` \| `openai` \| `gemini` \| `ollama` \| `enterprise-gateway`. |
| `--model`     | Override the LLM model.                                            |
| `--commit`    | Commit generated docs to the branch.                              |
| `--dry-run`   | Generate without writing to the repo (use with `--out`).           |
| `--out`       | Write docs to a preview directory instead of in place.             |

## GitHub Action usage

```yaml
- uses: actions/checkout@v4
- uses: Pablo-korea/repodocmake@v1
  with:
    files: "README,LICENSE,CONTRIBUTING,DEVELOPER_GUIDE"
    license: "Apache-2.0"
    mode: "pr"                 # pr | commit | check
    llm-provider: "anthropic"  # anthropic | openai | gemini | ollama | enterprise-gateway
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### Modes

| Mode     | Behavior                                            |
|----------|-----------------------------------------------------|
| `pr`     | Open a pull request with generated docs (default).  |
| `commit` | Commit generated docs directly to the branch.       |
| `check`  | Fail CI when docs are missing or drifted.           |

## LLM providers

One interface via [LiteLLM](https://github.com/BerriAI/litellm). Switch with a
single env var `REPODOCMAKE_LLM_PROVIDER`: `anthropic`, `openai`, `gemini`,
`ollama`, or `enterprise-gateway` (OpenAI-compatible, pre-wired).

## Development

```bash
pip install -e ".[dev]"
REPODOCMAKE_MOCK_LLM=1 pytest -q
ruff check src tests
```

See [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0.
