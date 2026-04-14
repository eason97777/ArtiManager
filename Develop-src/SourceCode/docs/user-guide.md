# ArtiManager User Guide

This guide covers the local CLI and web workflows shipped in `Develop-src/SourceCode/`.

ArtiManager is local-first. Your SQLite database, notes, scanned PDF metadata, analysis artifacts, and web workbench state are stored in configured local paths. Remote services are optional and are used only when a command needs them.

## Installation

Requirements:

- Python 3.11 or newer
- local filesystem access to your PDF folders
- optional API credentials for Claude, OpenAI, Zotero, DeepXiv, or local model services

Install for editable local use:

```bash
cd Develop-src/SourceCode
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Run tests:

```bash
pytest -q
```

Command entrypoint after editable install:

```bash
artimanager --help
```

During source-tree checks before installation, this equivalent form is useful:

```bash
PYTHONPATH=src python src/artimanager/cli/main.py --help
```

## Configuration

Start from the canonical example:

```bash
cp data/config.example.toml config.toml
```

Keep local `config.toml` files out of commits. The example stores only environment variable names for secrets.

Top-level settings:

- `scan_folders`: list of folders scanned for PDF files.
- `db_path`: SQLite database path. `scan` initializes this database when needed.
- `notes_root`: directory where Markdown notes and analysis artifacts are written.
- `template_path`: optional Markdown note template path. If set, make it valid from the directory where you run commands.
- `tracking_schedule`: default schedule label for new tracking rules.
- `log_level`: application log level.

Provider settings:

- `[agent]`: default provider for agent-backed commands. Supported values are `claude`, `openai`, `local`, and `mock`.
- `[agent.overrides.analysis]`: optional provider override for analysis commands. Missing fields fall back to `[agent]`.
- `[openai]`: OpenAI runtime transport options. `auth_mode` is `api_key_env` or `codex_chatgpt`.
- `[local]`: Ollama-compatible local endpoint settings.
- `[deepxiv]`: optional DeepXiv topic discovery settings.
- `[zotero]`: optional Zotero library settings.

Secret rule:

```bash
export ANTHROPIC_API_KEY="..."
export OPENAI_API_KEY="..."
export DEEPXIV_TOKEN="..."
export ZOTERO_API_KEY="..."
```

Do not paste real keys or tokens into `config.toml`, examples, notes, or docs.

## Provider Setup

Claude API key mode:

```toml
[agent]
provider = "claude"
model = "claude-sonnet-4-20250514"
api_key_env = "ANTHROPIC_API_KEY"
```

OpenAI direct API key mode:

```toml
[agent]
provider = "openai"
model = "gpt-5"
api_key_env = "OPENAI_API_KEY"

[openai]
auth_mode = "api_key_env"
base_url = "https://api.openai.com/v1"
timeout_seconds = 60
```

OpenAI Codex ChatGPT bridge mode:

```bash
codex login --device-auth
codex login status
```

```toml
[agent]
provider = "openai"
model = "gpt-5"
api_key_env = ""

[openai]
auth_mode = "codex_chatgpt"
codex_bin = "codex"
codex_auth_path = "~/.codex/auth.json"
timeout_seconds = 60
```

The bridge calls `codex exec` in a read-only temporary workspace. It requires ChatGPT/device auth and does not read undocumented Codex tokens.

Local Ollama-compatible mode:

```toml
[agent]
provider = "local"
model = "llama3.1"

[local]
endpoint = "http://localhost:11434"
timeout_seconds = 60
```

Start your local backend before running agent-backed commands.

## Core Library Workflow

Scan configured PDF folders and initialize the database:

```bash
artimanager scan --config config.toml
```

List inbox papers:

```bash
artimanager inbox --config config.toml
artimanager inbox --config config.toml --json-output
```

Search the library:

```bash
artimanager search "query text" --config config.toml
artimanager search "query text" --config config.toml --source metadata
artimanager search "query text" --config config.toml --source fulltext
artimanager search "note keyword" --config config.toml --source note
artimanager search "query text" --config config.toml --filter-tags gnn,benchmark
```

Rebuild search indexes:

```bash
artimanager reindex --config config.toml
```

Create and read Markdown notes:

```bash
artimanager note-create --config config.toml --paper-id <paper_id>
artimanager note-create --config config.toml --paper-id <paper_id> --title "Reading note"
artimanager note-show --config config.toml --paper-id <paper_id>
```

Attach and list manual tags:

```bash
artimanager tag-add --config config.toml --paper-id <paper_id> --tag "graph neural networks"
artimanager tag-add --config config.toml --paper-id <paper_id> --tag "dataset" --tag-type topic
artimanager tag-list --config config.toml --paper-id <paper_id>
artimanager tag-remove --config config.toml --paper-id <paper_id> --tag "dataset"
```

## Discovery Workflow

Topic discovery:

```bash
artimanager discover --config config.toml --topic "graph neural networks" --source semantic_scholar
artimanager discover --config config.toml --topic "graph neural networks" --source arxiv
artimanager discover --config config.toml --topic "graph neural networks for molecules" --source deepxiv
```

Paper-anchored discovery:

```bash
artimanager discover --config config.toml --paper-id <paper_id> --source semantic_scholar
artimanager discover --config config.toml --paper-id <paper_id> --source arxiv
```

DeepXiv is topic-only. `--paper-id ... --source deepxiv` returns a clear error by design.

Review discovery results:

```bash
artimanager discovery-inbox --config config.toml
artimanager discovery-inbox --config config.toml --status new
artimanager discovery-review <result_id> ignore --config config.toml
artimanager discovery-review <result_id> save_for_later --config config.toml
artimanager discovery-review <result_id> import --config config.toml
artimanager discovery-review <result_id> link_to_existing --config config.toml --link-to-paper <paper_id>
artimanager discovery-review <result_id> follow_author --config config.toml --author-name "Author Name"
```

Tracking-oriented review actions are also available for tracking-origin discovery rows:

```bash
artimanager discovery-review <result_id> mute_topic --config config.toml
artimanager discovery-review <result_id> snooze --config config.toml
```

## Tracking Workflow

Create rules:

```bash
artimanager tracking-create --config config.toml --name "GNN papers" --type topic --query "graph neural networks"
artimanager tracking-create --config config.toml --name "Author watch" --type author --query "Jane Smith"
artimanager tracking-create --config config.toml --name "cs.LG" --type category --query "cs.LG"
```

List, update, delete, and run rules:

```bash
artimanager tracking-list --config config.toml
artimanager tracking-update <rule_id> --config config.toml --disable
artimanager tracking-update <rule_id> --config config.toml --enable --query "updated query"
artimanager tracking-delete <rule_id> --config config.toml
artimanager tracking-run --config config.toml
artimanager tracking-run --config config.toml --rule-id <rule_id> --limit 10
```

Tracking writes candidates into the discovery inbox. It does not create a background daemon.

## Relationships And Validation

Create confirmed relationships manually:

```bash
artimanager relationship-create --config config.toml --source-paper <paper_id> --target-paper <paper_id> --type prior_work --evidence "Used as baseline"
artimanager relationship-list --config config.toml --paper-id <paper_id>
```

Suggest metadata-based relationships and review them:

```bash
artimanager relationship-suggest --config config.toml --paper-id <paper_id>
artimanager relationship-review <relationship_id> confirm --config config.toml
artimanager relationship-review <relationship_id> reject --config config.toml
```

Create and update validation records:

```bash
artimanager validation-create --config config.toml --paper-id <paper_id> --path /path/to/repo --repo-url https://example.invalid/repo.git --env-note "Python 3.11"
artimanager validation-update <validation_id> --config config.toml --outcome in_progress --summary "Environment created"
artimanager validation-update <validation_id> --config config.toml --outcome reproduced --summary "Main result reproduced"
```

Validation outcomes are `not_attempted`, `in_progress`, `reproduced`, `partially_reproduced`, and `failed`.

## Analysis Workflow

Single-paper analysis:

```bash
artimanager analysis-create --config config.toml --paper-id <paper_id> --prompt "Summarize the core contribution"
```

Compare two to five papers:

```bash
artimanager analysis-compare --config config.toml --paper-id <paper_a> --paper-id <paper_b> --prompt "Compare assumptions and evaluation"
```

Create agent-inferred relationship suggestions:

```bash
artimanager analysis-suggest --config config.toml --paper-id <paper_id> --mode related
artimanager analysis-suggest --config config.toml --paper-id <paper_id> --mode follow_up --candidate-paper-id <candidate_id>
```

List and show artifacts:

```bash
artimanager analysis-list --config config.toml
artimanager analysis-list --config config.toml --paper-id <paper_id>
artimanager analysis-show <analysis_id> --config config.toml
```

Analysis outputs are Markdown artifacts referenced by database records.

## Zotero Workflow

Configure Zotero only if you use Zotero integration:

```toml
[zotero]
library_id = "123456"
library_type = "user"
api_key_env = "ZOTERO_API_KEY"
```

Commands:

```bash
artimanager zotero-link --config config.toml --paper-id <paper_id> --zotero-key <item_key>
artimanager zotero-show --config config.toml --paper-id <paper_id>
artimanager zotero-sync --config config.toml --dry-run
artimanager zotero-sync --config config.toml
```

## Web Workbench

Launch:

```bash
artimanager web --config config.toml
artimanager web --config config.toml --host 127.0.0.1 --port 8099
```

Available pages:

- dashboard
- inbox
- search
- paper detail
- discovery inbox
- tracking rules
- relationship review queue
- analysis list and detail

Browser actions available:

- discovery review actions
- tracking rule create, update, delete, and run
- relationship confirm and reject
- paper-detail inspection of notes, validations, analysis artifacts, and relationships

Actions intentionally left to CLI, editor, or Zotero:

- editing Markdown note content
- creating validation records
- generating analysis artifacts
- OS-level opening of local files
- Zotero item management

## Troubleshooting

Database not found:

Run `scan --config config.toml` first. Most read commands expect `db_path` to exist.

Missing API key environment variable:

Check that the config stores the environment variable name and your shell exports the value. Example: `api_key_env = "ANTHROPIC_API_KEY"` plus `export ANTHROPIC_API_KEY="..."`.

Codex not installed:

Install Codex CLI and make sure `codex` is on `PATH`, or set `[openai].codex_bin`.

Codex not logged in:

Run `codex login --device-auth`, then `codex login status`.

Incompatible Codex auth mode:

The `codex_chatgpt` bridge requires ChatGPT/device auth. API-key auth inside Codex auth metadata is rejected.

DeepXiv disabled or missing token:

Set `[deepxiv].enabled = true`, set `api_token_env = "DEEPXIV_TOKEN"`, and export `DEEPXIV_TOKEN`.

DeepXiv upstream or network failures:

The CLI reports a clear runtime error. Retry later or use `semantic_scholar` / `arxiv` while the upstream service is unavailable.

Local Ollama endpoint unavailable:

Start your local model server and confirm `[local].endpoint` is correct. The provider calls an Ollama-compatible `/api/generate` endpoint.

No search results:

Run `scan` first, then `reindex`. For note search, create notes with `note-create` or ensure existing note files are linked in the database before reindexing.

Command mismatch:

Run `artimanager <command> --help` and prefer the help output over older notes or shell history.
