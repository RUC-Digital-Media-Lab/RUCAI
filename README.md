# RUCAI

[![DOI](https://zenodo.org/badge/1162919450.svg)](https://doi.org/10.5281/zenodo.20622874)

RUCAI is a self-hosted course AI application for teachers who want a chat
interface grounded in their own course materials. A teacher can create a course
workspace, upload PDF and DOCX readings, ask questions against those materials,
and publish password-protected student chat instances based on selected course
content.

The project is research software developed for a pilot teaching context. It is
intended for institution-controlled deployment and source-grounded course use,
not as a general-purpose chatbot or a replacement for local data, copyright, and
student privacy review.

## Main Features

- Course workspaces with editable course prompts and active-course selection.
- PDF and DOCX upload with asynchronous ingestion jobs.
- Retrieval-augmented chat over uploaded course materials.
- Source-oriented answer display so teachers and students can trace responses
  back to course texts.
- Student instances that expose selected course material through a separate
  password-protected chat interface.
- Local model serving through Ollama for embeddings and chat models.
- PostgreSQL plus pgvector storage for courses, documents, chunks, messages, and
  student instances.
- Optional analytics and deployment helpers for institutional VM deployment.

## Architecture

RUCAI is built around a small FastAPI application:

- `app/main.py` serves the API and the bundled teacher/student web interfaces.
- `app/ingest.py` extracts and chunks PDF/DOCX course material.
- `app/embeddings.py`, `app/search.py`, and `app/chat.py` handle embedding,
  retrieval, and answer generation.
- `app/db.py` creates and updates the PostgreSQL schema at application startup.
- `deploy/` contains helper scripts for Ubuntu VM deployment, PostgreSQL/pgvector
  setup, systemd service management, and tunnel-based public access.

The default model setup uses Ollama with `bge-m3` for embeddings and
`gemma3:12b` for chat, but these can be changed through environment variables.

## Requirements

- Python 3 with virtual environment support.
- PostgreSQL with the `pgvector` extension enabled.
- Ollama or a compatible local Ollama endpoint.
- Enough CPU/GPU memory for the selected chat model.
- Optional: MinerU installed on `PATH` if you want to use the MinerU fallback for
  difficult scanned PDFs.

## Quick Start

Clone the repository and install the Python dependencies:

```bash
git clone https://github.com/Frederikmh90/RUCAI.git
cd RUCAI
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Create a local configuration file:

```bash
cp .env.example .env
```

Edit `.env` before running the app. At minimum, check the database connection,
Ollama URL, model names, and authentication values:

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=ppl_rag
DB_USER=ppl
DB_PASSWORD=change-this
OLLAMA_BASE_URL=http://localhost:11434
EMBED_MODEL=bge-m3
CHAT_MODEL=gemma3:12b
AUTH_USERNAME=teacher
AUTH_PASSWORD=change-this
```

Create a PostgreSQL database and enable pgvector. The exact commands depend on
your local PostgreSQL setup, but the database, user, and password must match
`.env`, and the target database must have the vector extension:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Pull the default Ollama models, or replace them in `.env` with models already
available on your server:

```bash
ollama pull bge-m3
ollama pull gemma3:12b
```

Start the application:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8011
```

Then open:

```text
http://localhost:8011
```

On startup, RUCAI creates the required application tables if the configured
database is reachable and `pgvector` is available.

## Basic Use

1. Log in with the teacher credentials from `.env`.
2. Create or activate a course workspace.
3. Upload PDF or DOCX course materials and wait for ingestion to finish.
4. Ask questions in the teacher chat and inspect the displayed sources.
5. Publish a student instance when you want students to access a selected course
   material set through the student interface.

The student interface is available at `/student` and through generated instance
links.

## Deployment Notes

The `deploy/` directory contains scripts used for an Ubuntu VM deployment. They
are provided as operational helpers, not as a universal production installer.
Review and adapt them before using them on institutional infrastructure.

For a fresh apt-based VM, the intended flow is:

```bash
APP_DIR=/path/to/RUCAI bash deploy/scripts/bootstrap_new_vm.sh
APP_DIR=/path/to/RUCAI DB_PASSWORD='set-a-strong-password' bash deploy/scripts/setup_local_postgres.sh
SKIP_GIT=1 APP_DIR=/path/to/RUCAI BRANCH=main bash deploy/scripts/deploy_green.sh
```

The deployment scripts assume a local checkout, a configured `.env`, and an
institution-specific decision about public access, reverse tunnels, DNS, TLS, and
server operations.

## Configuration Reference

Common environment variables:

| Variable | Purpose |
| --- | --- |
| `DATA_ROOT` | Local application data directory. |
| `UPLOAD_ROOT` | Uploaded source document directory. |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | PostgreSQL connection settings. |
| `OLLAMA_BASE_URL` | Ollama endpoint used for embeddings and chat. |
| `EMBED_MODEL` | Embedding model name. |
| `CHAT_MODEL` | Chat model name. |
| `AUTH_USERNAME`, `AUTH_PASSWORD` | Default teacher login credentials. |
| `AUTH_USERS_FILE` | Optional file for persisted teacher users. |
| `AUTH_TTL_SECONDS` | Teacher session lifetime. |
| `UMAMI_*` | Optional analytics configuration. |

See `.env.example` for the full current configuration surface.

## Testing

Run the test suite with:

```bash
pytest
```

For release preparation, also test installation in a fresh virtual environment,
confirm that no private `.env` or uploaded course material is committed, and
review deployment scripts against the target institution's infrastructure.

## Data, Privacy, and Copyright

RUCAI is designed for institution-controlled use, but operators remain
responsible for deciding which course materials may be uploaded, how long data is
retained, who may access student instances, and whether the selected model
serving setup complies with local privacy and copyright rules.

The application cannot prevent users from copying text out of RUCAI and pasting
it into other systems. This should be handled through course policy,
institutional guidance, and teaching practice.

## License

RUCAI is released under the MIT License. See `LICENSE`.
