# ArtiManager

ArtiManager is a local-first literature workspace for managing PDFs, notes, discovery results, relationships, validation records, tracking rules, and agent-generated analysis artifacts.

The project keeps ownership of your library on your machine. PDFs, notes, the SQLite database, and generated artifacts live in paths you configure. API keys and service tokens are read from environment variables only; do not write secrets into config files, docs, notes, or commits.

## Quickstart

From a fresh checkout:

```bash
cd Develop-src/SourceCode
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp data/config.example.toml config.toml
```

Edit `config.toml`:

- set `scan_folders` to the folders containing your PDFs
- set `db_path` to the SQLite database path you want to use
- set `notes_root` to the directory where Markdown notes should be created
- set provider environment variable names, not actual keys

The normal first command initializes the database and scans PDFs:

```bash
artimanager scan --config config.toml
```

Repeated scans are safe: unchanged files are not duplicated, changed files at the same path refresh the registered file asset, and copied duplicate PDFs are linked as duplicate assets for the existing paper. Title extraction is best-effort and falls back from obviously bad PDF metadata when possible.

All examples below use the installed `artimanager` console script. For source-tree verification before installation, use `PYTHONPATH=src python src/artimanager/cli/main.py --help`.

## Short End-To-End Flow

```bash
artimanager scan --config config.toml
artimanager inbox --config config.toml
artimanager search "graph neural networks" --config config.toml
artimanager note-create --config config.toml --paper-id <paper_id>
artimanager tag-add --config config.toml --paper-id <paper_id> --tag "gnn"
artimanager tag-list --config config.toml --paper-id <paper_id>
artimanager discover --config config.toml --topic "graph neural networks" --source arxiv
artimanager web --config config.toml
```

Open the web workbench at `http://127.0.0.1:8000` after the `web` command starts.

Paper detail pages show registered file paths with copy buttons and, where supported, an `Open locally` action. Local open is limited to file assets already stored in the database; if it fails, copy the visible path and open it manually. Zotero handoff on paper detail exposes the linked library metadata and item key for copying, but does not control or modify Zotero.

High-frequency triage is available from Web paper detail: controlled paper states, manual metadata correction, tag add/remove, create missing Markdown note, and validation metadata record creation. The same controlled state and metadata rules are available from `artimanager paper-update`.

The Web search page also acts as a paper browser for state filters. Use links such as `/search?status=archived` or the visible Inbox/Active/Archived/Ignored shortcuts to recover papers after quick state actions move them out of inbox.

The web workbench intentionally exposes only selected small review, metadata, and handoff actions. CLI remains the source of truth for online discovery runs, validation experiment work, analysis generation, and relationship suggestion generation until those workflows have a local job runner with status, logs, retries, and failure reporting.

## Configuration

Use `data/config.example.toml` as the canonical starting point. Copy it to a local `config.toml` and keep that local file out of commits.

Provider secrets are configured by environment variable name:

```bash
export ANTHROPIC_API_KEY="..."
export OPENAI_API_KEY="..."
export DEEPXIV_TOKEN="..."
export ZOTERO_API_KEY="..."
```

For Codex ChatGPT bridge mode, install Codex CLI and authenticate with:

```bash
codex login --device-auth
```

## Provider Modes

Configure the default provider in `[agent]`:

- `provider = "claude"` uses `api_key_env = "ANTHROPIC_API_KEY"`.
- `provider = "openai"` with `[openai].auth_mode = "api_key_env"` uses `api_key_env = "OPENAI_API_KEY"`.
- `provider = "openai"` with `[openai].auth_mode = "codex_chatgpt"` uses the official Codex CLI login instead of a project API key.
- `provider = "local"` calls an Ollama-compatible local `/api/generate` endpoint configured in `[local]`.
- `provider = "mock"` is useful for tests and dry local workflows.

## DeepXiv

DeepXiv is an optional discovery source. Enable it only when you have a token:

```toml
[deepxiv]
enabled = true
api_token_env = "DEEPXIV_TOKEN"
```

```bash
export DEEPXIV_TOKEN="..."
artimanager discover --config config.toml --topic "graph neural networks for molecules" --source deepxiv
```

DeepXiv is topic-only in this release; paper-anchored DeepXiv discovery intentionally returns a clear error.

## Zotero

Zotero is optional and read-only from ArtiManager's side. Configure it with an environment variable name, not a real key:

```toml
[zotero]
library_id = "1234567"
library_type = "user"
api_key_env = "ZOTERO_API_KEY"
```

```bash
export ZOTERO_API_KEY="..."
artimanager zotero-link --config config.toml --paper-id <paper_id> --zotero-key <item_key>
artimanager zotero-show --config config.toml --paper-id <paper_id>
artimanager zotero-sync --config config.toml --dry-run
```

The `library_id` is your Zotero `userID` for personal libraries or the numeric group ID for group libraries. The `--zotero-key` value is the Zotero item key, not a DOI or arXiv ID. Current Zotero support links existing items and fills blank local metadata fields only; it does not create Zotero items, write back to Zotero, sync attachments, import Zotero notes into Markdown, or auto-match papers.

## Documentation

Read [docs/user-guide.md](docs/user-guide.md) for:

- installation and runtime assumptions
- all config sections
- Claude, OpenAI, Codex ChatGPT bridge, and local provider setup
- CLI workflows for scan/search/notes/tags/discovery/tracking/relationships/validation/analysis
- web workbench usage
- troubleshooting

## Development Checks

Run the test suite from `Develop-src/SourceCode/`:

```bash
pytest -q
```

Useful CLI help checks:

```bash
PYTHONPATH=src python src/artimanager/cli/main.py --help
PYTHONPATH=src python src/artimanager/cli/main.py discover --help
PYTHONPATH=src python src/artimanager/cli/main.py web --help
PYTHONPATH=src python src/artimanager/cli/main.py analysis-create --help
PYTHONPATH=src python src/artimanager/cli/main.py tag-add --help
```
