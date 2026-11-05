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

The `.venv` folder is local to this checkout and is excluded from Git. Repeat
the setup commands on each computer; do not copy the environment between
computers.
