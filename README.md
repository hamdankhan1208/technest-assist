# TechNest Assist

TechNest Assist is a prototype AI assistant for a technology retailer. The
repository currently contains a repeatable sample-data generator and a small
LLM connectivity example using Groq with local Ollama fallback.

> **Project status:** The customer-support application and policy-grounded
> retrieval (RAG) flow are not implemented yet. The LLM example is a smoke test,
> not a source-grounded customer-support system.

## Current capabilities

- Start PostgreSQL, Qdrant, and Mailpit locally with Docker Compose.
- Generate sample product records, product datasheets, policy documents,
  certificates, and tender documents.
- Call a Groq chat model when configured, with Ollama as a fallback.
- Run tests for LLM provider selection and fallback behavior.

## Technology

- Python
- PostgreSQL
- Qdrant
- Groq API and Ollama
- Docker Compose

## Prerequisites

- Python 3.12
- Docker Desktop with Docker Compose
- Ollama, if you want to use the local model or Groq fallback
- A Groq API key, if you want to use Groq (optional)

The full `requirements.txt` includes machine-learning packages such as PyTorch
and sentence-transformers, so the initial installation may take some time and
disk space.

## Setup

In PowerShell, from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Start the local services:

```powershell
docker compose up -d
```

The services are available at:

| Service | Address |
| --- | --- |
| PostgreSQL | `localhost:5432` |
| Qdrant HTTP API | `http://localhost:6333` |
| Qdrant gRPC | `localhost:6334` |
| Mailpit web UI | `http://localhost:8025` |
| Mailpit SMTP | `localhost:1025` |

## Generate sample data

```powershell
.\.venv\Scripts\python.exe .\seed_data.py
```

The script generates 200 sample products, product datasheets, three policy
documents, certificates, and three tender documents with 15–20 requirements
each. It also writes expected tender answers to
`data/tender_answer_key.xlsx` and upserts product records in PostgreSQL.

The seed script uses the PostgreSQL settings below by default. Override them
with environment variables if your local database uses different values:

| Variable | Default |
| --- | --- |
| `PGHOST` | `localhost` |
| `PGPORT` | `5432` |
| `PGDATABASE` | `technest_db` |
| `PGUSER` | `technest_user` |
| `PGPASSWORD` | `technest_password` |

## Run the LLM example

### Groq

Set your API key in the current PowerShell session, then run the example:

```powershell
$env:GROQ_API_KEY = "your-groq-api-key"
.\.venv\Scripts\python.exe .\first_llm_call.py
```

The default Groq model is `openai/gpt-oss-120b`. To select another model, set
`GROQ_MODEL` before running the script.

### Ollama

Install Ollama, download the default model, and run the example:

```powershell
ollama pull llama3.2:1b
.\.venv\Scripts\python.exe .\first_llm_call.py
```

When `GROQ_API_KEY` is not set, the script uses Ollama directly. If a Groq
request fails, it reports the error and tries Ollama. The default local model
is `llama3.2:1b`; set `OLLAMA_MODEL` to use another model already installed in
Ollama.

## Run tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Repository layout

```text
.
├── data/                 # Generated sample documents and spreadsheets
├── tests/                # Automated tests
├── docker-compose.yml    # Local PostgreSQL, Qdrant, and Mailpit services
├── first_llm_call.py     # Groq/Ollama connectivity example
├── requirements.txt      # Python dependencies
└── seed_data.py          # Sample data and database seeding
```

## Important notes

- The credentials in `docker-compose.yml` are for local development only. Do
  not use them in a production deployment.
- The seed script updates generated products in the `TN-LAP-*`, `TN-MON-*`,
  and `TN-OFF-*` sample-code namespaces. It does not drop the products table.
- Generated data and local database contents are for development and testing;
  they are not production catalog or policy data.
