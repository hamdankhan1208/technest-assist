# TechNest Assist

## Set up Python on Windows

The virtual environment keeps this project's Python libraries in the project
folder, so installing them does not require administrator rights. Install
Python 3.12 for your Windows user (not for all users) first. Python 3.15 does
not yet have Windows wheels for every dependency, which can make pip try to
build packages using administrator-level C++ tools. A virtual environment does
not include the Python interpreter.

If `.venv` was already created with another Python version, deactivate it and
remove that `.venv` folder before recreating it. Then open PowerShell in this
project folder and run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, use the environment's Python directly instead:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Run the seed script with the environment active:

```powershell
python .\seed_data.py
```

The script generates a repeatable set of 200 products, matching datasheets and
certificates, three policies, and three tenders with 15–20 distinct product
requirements each. Tenders include Yes, Partly, and No cases; their expected
results and evidence are written to `data/tender_answer_key.xlsx`. It upserts
generated products and removes only obsolete sample product codes in the
`TN-LAP-*`, `TN-MON-*`, and `TN-OFF-*` namespaces; it does not drop the
products table. PostgreSQL connection settings default to the values in
`docker-compose.yml` and can be overridden with `PGHOST`, `PGPORT`,
`PGDATABASE`, `PGUSER`, and `PGPASSWORD`.

## LLM providers

When `GROQ_API_KEY` is set in the environment, the example uses Groq first. If
the Groq request fails, it reports the failure and falls back to local Ollama.
If the key is not set, it uses Ollama directly. Keep the API key out of source
control.

Set `GROQ_API_KEY` in your PowerShell session or user environment to enable the
Groq path. Set `GROQ_MODEL` to select another Groq model; the default is
`openai/gpt-oss-120b`.

Install and start Ollama, and make sure the `llama3.2:1b` model is available
for local use or as a fallback:

```powershell
ollama run llama3.2:1b
```

After confirming the model responds, exit the interactive session with `/bye`.
Run the Python example using the project environment:

```powershell
.\.venv\Scripts\python.exe .\first_llm_call.py
```

To use a different model already installed in Ollama, set `OLLAMA_MODEL` in
PowerShell before running the example, for example
`$env:OLLAMA_MODEL = "llama3.2"`.

The `.venv` folder is local to this checkout and is excluded from Git. Repeat
the setup commands on each computer; do not copy the environment between
computers.
