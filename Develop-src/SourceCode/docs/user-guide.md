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

Repeated scans are safe and idempotent:

- unchanged files at the same absolute path are reported as unchanged and are not duplicated
- changed files at the same absolute path refresh the existing `file_assets` row without destructively relinking it to another paper
- copied duplicate PDFs at new paths are attached as duplicate file assets for the existing paper
- title extraction falls back from low-quality PDF metadata to plausible first-page title text when possible

PDF metadata extraction is best-effort. Difficult or malformed PDFs may still need manual metadata correction.

List inbox papers:

```bash
artimanager inbox --config config.toml
artimanager inbox --config config.toml --json-output
```

Update paper triage states or manually corrected metadata:

```bash
artimanager paper-update --config config.toml --paper-id <paper_id> --workflow-status active
artimanager paper-update --config config.toml --paper-id <paper_id> --reading-state read
artimanager paper-update --config config.toml --paper-id <paper_id> --research-state relevant
artimanager paper-update --config config.toml --paper-id <paper_id> --title "Corrected title"
```

State values are controlled. Supported values are:

- `workflow_status`: `inbox`, `active`, `archived`, `ignored`
- `reading_state`: `to_read`, `reading`, `read`, `skimmed`, `deferred`
- `research_state`: `untriaged`, `relevant`, `background`, `maybe`, `not_relevant`

Search the library:

```bash
artimanager search "query text" --config config.toml
artimanager search "query text" --config config.toml --source metadata
artimanager search "query text" --config config.toml --source fulltext
artimanager search "note keyword" --config config.toml --source note
artimanager search "query text" --config config.toml --filter-tags gnn,benchmark
```

In the Web workbench, `/search` also works as a paper browser when you leave the query blank and use filters. For example, `/search?status=archived` lists archived papers so papers moved out of inbox can still be found without knowing their direct URL.

Rebuild search indexes:

```bash
artimanager reindex --config config.toml
```

Create and read Markdown notes:

```bash
artimanager note-create --config config.toml --paper-id <paper_id>
artimanager note-create --config config.toml --paper-id <paper_id> --title "Reading note"
artimanager note-create --config config.toml --paper-id <paper_id> --filename reading-note.md
artimanager note-show --config config.toml --paper-id <paper_id>
```

Markdown notes are `.md` reading/research notes under `notes_root`. The filename may be selected safely at creation time and renamed safely from the paper detail page later. Do not store notebooks as Markdown notes.

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
artimanager discovery-inbox --config config.toml --json-output
artimanager discovery-review <result_id> ignore --config config.toml
artimanager discovery-review <result_id> save_for_later --config config.toml
artimanager discovery-review <result_id> import --config config.toml
artimanager discovery-review <result_id> link_to_existing --config config.toml --link-to-paper <paper_id>
artimanager discovery-review <result_id> follow_author --config config.toml --author-name "Author Name"
```

Discovery candidates are deduplicated by DOI, then arXiv ID, then source/external ID. New discovery and tracking writes also store provenance rows in `discovery_result_sources`, so one inbox candidate can preserve multiple reasons for appearing. `discovery-inbox --json-output` includes a `provenance` array for each result. Existing pre-provenance rows do not need backfill.

The Web discovery inbox shows a `Why shown` area for each candidate. It can display topic discovery, paper-anchored discovery, citation tracking, and OpenAlex author watch provenance. Older candidates without provenance show `No provenance recorded`.

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
artimanager tracking-create --config config.toml --name "Citations of p1" --type citation --paper-id p1 --direction cited_by --limit 20
artimanager tracking-create --config config.toml --name "References from p1" --type citation --paper-id p1 --direction references
artimanager tracking-create --config config.toml --name "Alice OpenAlex" --type openalex_author --author-id A123456789 --display-name "Alice Smith" --limit 20
```

Citation tracking rules use Semantic Scholar and store a canonical JSON payload in `tracking_rules.query`:

```json
{"direction":"cited_by","limit":20,"paper_id":"p1","schema_version":1,"source":"semantic_scholar"}
```

Citation rule requirements:

- `paper_id` must exist locally and have a DOI or arXiv ID.
- `direction` must be `cited_by` or `references`.
- `source` is `semantic_scholar` for this MVP.
- Rule-level `limit` is clamped to `1..100`; `tracking-run --limit` remains the runtime cap.
- Advanced creation can pass `--query` JSON instead of `--paper-id` and `--direction`, but not both.

OpenAlex author identity tracking stores a single stable author ID in canonical JSON:

```json
{"author_id":"https://openalex.org/A123456789","display_name":"Alice Smith","limit":20,"schema_version":1,"source":"openalex"}
```

OpenAlex author rule requirements:

- `author_id` must be a stable OpenAlex author ID such as `A123456789` or `https://openalex.org/A123456789`; it is persisted as the full URL form.
- `display_name` is optional readability metadata only and is never used as identity.
- `source` is `openalex`.
- Rule-level `limit` is clamped to `1..100`; `tracking-run --limit` remains the runtime cap.
- Raw author names, multiple author IDs, institution IDs, seed-paper modes, and coauthor-depth expansion are rejected in this MVP.

List, update, delete, and run rules:

```bash
artimanager tracking-list --config config.toml
artimanager tracking-update <rule_id> --config config.toml --disable
artimanager tracking-update <rule_id> --config config.toml --enable --query "updated query"
artimanager tracking-delete <rule_id> --config config.toml
artimanager tracking-run --config config.toml
artimanager tracking-run --config config.toml --rule-id <rule_id> --limit 10
```

Keyword, topic, author, and category tracking use arXiv and may create the existing local relevance summary. Citation and OpenAlex author tracking are different: they are fetch + dedupe + provenance only, do not call the configured LLM provider summarizer, and do not send local PDFs, notes, or full text to external sources.

Tracking writes candidates into the discovery inbox and records the tracking rule provenance that produced each candidate. Citation provenance records include the local anchor paper, Semantic Scholar anchor identifier, direction, source, and candidate external ID. OpenAlex author provenance records include `source = openalex`, `direction = openalex_author_work`, normalized `anchor_author_id`, and the OpenAlex work ID as `source_external_id`. Tracking does not create a background daemon.

In Web, the tracking rules page keeps raw `query` JSON editable and adds a readable summary for each rule. Citation summaries show direction, anchor paper, source, and limit. OpenAlex author summaries show display name when present, normalized author ID, source, and limit. The Web page does not add ergonomic citation/OpenAlex creation forms; use CLI for those rules.

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

Use `validation_records.path` for local validation workspaces, notebooks, scripts, or artifacts. A `.ipynb` path is treated as a validation notebook artifact, not a Markdown note. Registering a path does not require it to exist yet and does not run anything.

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
library_id = "1234567"
library_type = "user"
api_key_env = "ZOTERO_API_KEY"
```

`api_key_env` is the environment variable name only. Never paste the real Zotero API key into `config.toml`.

Set the real key in your shell:

```bash
export ZOTERO_API_KEY="..."
```

Create a Zotero API key from Zotero web:

- log into Zotero
- open `https://www.zotero.org/settings/keys`
- create a new private key
- read access is sufficient for the current ArtiManager integration

For a personal library, use your Zotero `userID` as `library_id` and set `library_type = "user"`. The `userID` is shown on the Zotero API keys/settings page.

For a group library, use the numeric group ID as `library_id` and set `library_type = "group"`. Group IDs appear in Zotero group/API URLs as `/groups/<groupID>`.

The `--zotero-key` value is the Zotero item key. It is not a DOI and not an arXiv ID. You can find it from Zotero web item URLs, Zotero API data, or item metadata exposed by API tools.

Commands:

```bash
artimanager zotero-link --config config.toml --paper-id <paper_id> --zotero-key <item_key>
artimanager zotero-show --config config.toml --paper-id <paper_id>
artimanager zotero-sync --config config.toml --dry-run
artimanager zotero-sync --config config.toml
```

Current capabilities:

- `zotero-link` links a local `paper_id` to a Zotero item key, writes `zotero_links`, updates `papers.zotero_item_key`, fetches the Zotero item, and fills blank local metadata fields.
- `zotero-show` shows the existing local Zotero link, fetches Zotero item metadata when API config is available, and displays child note count/summary.
- `zotero-sync` iterates linked papers, fetches each Zotero item, fills blank local metadata fields, and supports `--dry-run`.

Current boundaries:

- ArtiManager does not write local changes back to Zotero.
- ArtiManager does not create Zotero items.
- ArtiManager does not upload or sync PDF attachments.
- ArtiManager does not import Zotero notes into local Markdown notes.
- ArtiManager does not sync Zotero tags into local tag tables.
- ArtiManager does not automatically match local papers to Zotero items by DOI, title, or arXiv ID.
- Metadata sync fills blank local fields only; it does not overwrite populated local fields.

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
- paper-detail state updates for workflow, reading, and research status
- paper-detail manual metadata correction for title, authors, year, DOI, arXiv ID, and abstract
- paper-detail tag list/add/remove controls
- paper-detail create-note action when a Markdown note is missing, with safe `.md` filename selection
- paper-detail Markdown note title update and safe filename rename
- paper-detail validation metadata/artifact path record creation
- paper-detail inspection of notes, validations, analysis artifacts, and relationships
- paper-detail local handoff for registered file assets, Markdown notes, and validation paths: visible path, copy path, and local open where supported
- paper-detail Zotero handoff: visible library metadata, item key, and copy item key
- discovery inbox provenance display for recorded discovery/tracking reasons
- paper-detail discovery-origin provenance display when the paper came from discovery import/link
- tracking rule readable summaries for citation and OpenAlex payloads while preserving raw query editing

Actions intentionally left to CLI, editor, or Zotero:

- editing Markdown note content
- generating analysis artifacts
- opening arbitrary local paths that are not registered in the database
- running validation experiments or notebooks
- creating citation/OpenAlex author tracking rules from Web ergonomic forms
- Zotero item management

Paper detail handoff limits:

- Local open is only available for file assets, Markdown notes, and validation paths already registered in the database.
- Open routes look up the path by record IDs such as `paper_id + file_id`, `paper_id + note_id`, or `paper_id + validation_id`; they do not accept arbitrary path input.
- The file or directory must still exist on disk. If local open fails, copy the visible path and open it manually.
- Opening a registered `.ipynb` path uses the OS default handler only; ArtiManager does not create, edit, execute, or serve notebooks from Web.
- Zotero handoff exposes/copies the linked item key and library metadata only; it does not control Zotero, modify Zotero items, import notes, sync tags, or sync attachments.

### Web Invocation Boundary

The web workbench is a local review and handoff surface, not a replacement for every CLI command.

Web-triggerable actions currently stay narrow:

- discovery inbox review actions
- tracking rule create, update, delete, and run
- relationship confirm and reject
- paper-detail state updates, manual metadata correction, tag add/remove controls
- paper-detail creation/update of Markdown note metadata and safe Markdown filenames
- paper-detail creation of validation metadata records and registered artifact paths
- paper-detail local handoff for registered file assets, Markdown notes, and validation paths
- paper-detail Zotero item key handoff

CLI remains the source of truth for broader workflow commands:

- online discovery runs
- validation experiment execution and notebook/workspace work
- Markdown note content editing
- analysis generation and comparison
- relationship suggestion generation
- any long-running provider-backed or network-backed operation not explicitly exposed as a safe web route

This boundary is intentional. Long-running commands need job status, logs, cancellation, retries, and failure recovery before they become safe browser actions. Provider-backed commands also need credential and configuration diagnostics in the UI. Commands that write files or accept local paths need narrow validation and clear local-only security boundaries.

Future web invocation should use a local job runner rather than shelling out from Web to CLI. A job runner should track job type, parameters, status, started and finished timestamps, stdout/stderr or structured logs, created artifact/result references, and failure messages.

Good future job-runner candidates include topic discovery, single-paper analysis creation, multi-paper comparison, and relationship suggestion generation. Small direct web actions are acceptable when they remain bounded local DB/file operations with strict input validation and shared manager logic.

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
