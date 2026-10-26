# Installation

groundfault is a pure Python package. It runs on Windows, macOS and Linux and needs no compiler.

## Requirements

* **Python 3.10 or newer.** The continuous integration tests Python 3.10 to 3.14 on Linux, 3.12 on Windows and 3.13
  on macOS, and the lowest declared versions of all dependencies on Python 3.10.
* The core dependencies are installed automatically: NumPy ≥ 1.24, pandas ≥ 2.0, Matplotlib ≥ 3.7 and SciPy ≥ 1.10.
* [Git](https://git-scm.com/) to install from GitHub or to clone the repository.
* Optionally a [groundmeas](https://github.com/Ce1ectric/groundmeas) database with earthing measurements (see
  [below](#the-groundmeas-database-optional)); groundmeas itself does not have to be installed.

## Installing with pip

For scripts and your own evaluations, install the package with all optional features of the library (extra `all`)
directly from GitHub:

```bash
pip install "groundfault[all] @ git+https://github.com/Ce1ectric/groundfault"
```

For the notebooks, use the extra `notebook` instead (it adds JupyterLab and the kernel package; see the
[recommended setup](#recommended-setup-with-uv)). Or clone the repository and install it in editable mode – then the
notebooks (`notebooks/`), the tools (`tools/`) and the tests are at hand as well, and changes to the source take effect
without reinstalling:

```bash
git clone https://github.com/Ce1ectric/groundfault.git
cd groundfault
pip install -e ".[dev]"
```

Use a virtual environment for either way (the [recommended setup](#recommended-setup-with-uv) below shows how). A
system Python often refuses to install packages (`error: externally-managed-environment`).

Check the installation:

```bash
python -c "import groundfault; print(groundfault.__version__)"
```

```text
3.6.0
```

## Optional extras

The core package evaluates recordings, writes result files, report figures (Matplotlib) and CSV/Markdown tables.
Further features need optional dependencies, grouped as extras in `pyproject.toml`:

| Extra | Installs | Needed for |
|---|---|---|
| `interactive` | plotly, ipywidgets, jinja2 | interactive figures (`groundfault.interactive`), the [signal explorer](../user-guide/explorer.md) in the notebook (controls: ipywidgets, formatted tables: jinja2) and as an HTML file (Plotly) |
| `export` | openpyxl, python-docx | the Excel workbook and the Word file of the exported tables (`report.export_tables`; without them only CSV and Markdown are written, with a warning) and the [Word report of a campaign](../user-guide/document.md) (`groundfault.document`) |
| `all` | `interactive` + `export` | everything the package can do – the usual choice for scripts |
| `notebook` | `interactive` + `export`, JupyterLab, ipykernel | working with the [notebooks](../user-guide/notebooks.md) |
| `dev` | `interactive` + `export`, pytest, ruff, nbformat, nbclient, ipykernel | development: running the tests, linting, regenerating the notebooks (`tools/make_notebooks.py`) |
| `docs` | mkdocs-material, mkdocstrings[python], ruff | building this documentation (ruff formats the signatures in the API reference) |

Extras can be combined, e.g. `pip install -e ".[dev,docs]"`.

## Recommended setup with uv

For daily work with the notebooks we recommend [uv](https://docs.astral.sh/uv/), a fast installer that also provides
the Python interpreter, and **one virtual environment outside cloud-synchronised folders**. Campaign data usually live
in a shared, synchronised folder (Nextcloud, OneDrive, Dropbox …) – the environment does not belong there: it consists
of thousands of small files that the sync client would upload and may lock during an installation, and it only works
on the computer it was created on anyway. Keep the campaigns and your working copies of the notebooks in the
synchronised work folder, and the environment (and a clone of the repository) in your home directory.

=== "macOS / Linux"

    ```bash
    # 1  install uv (or: brew install uv)
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # 2  get the repository: package, notebooks and tools
    git clone https://github.com/Ce1ectric/groundfault.git ~/src/groundfault

    # 3  create the environment (uv downloads Python 3.13 if needed) and install groundfault into it
    uv venv --python 3.13 ~/.venvs/groundfault
    cd ~/src/groundfault
    uv pip install --python ~/.venvs/groundfault/bin/python -e ".[notebook]"

    # 4  register the environment as a Jupyter kernel
    ~/.venvs/groundfault/bin/python -m ipykernel install --user --name groundfault --display-name "Python (groundfault)"
    ```

=== "Windows (PowerShell)"

    ```powershell
    # 1  install uv (or: winget install --id=astral-sh.uv -e)
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

    # 2  get the repository: package, notebooks and tools
    git clone https://github.com/Ce1ectric/groundfault.git $HOME\src\groundfault

    # 3  create the environment (uv downloads Python 3.13 if needed) and install groundfault into it
    uv venv --python 3.13 $HOME\.venvs\groundfault
    cd $HOME\src\groundfault
    uv pip install --python $HOME\.venvs\groundfault\Scripts\python.exe -e ".[notebook]"

    # 4  register the environment as a Jupyter kernel
    & $HOME\.venvs\groundfault\Scripts\python.exe -m ipykernel install --user --name groundfault --display-name "Python (groundfault)"
    ```

Open a new terminal after installing uv, so that the `uv` command is found. If you need neither the notebooks nor the
tools of the repository, skip step 2 and install from GitHub in step 3:
`uv pip install --python <environment python> "groundfault[notebook] @ git+https://github.com/Ce1ectric/groundfault"`
for your own notebooks (keep step 4), or `"groundfault[all] @ git+https://github.com/Ce1ectric/groundfault"` for
scripts only (step 4 is not needed).

!!! tip "Call the environment by its full path"
    `~/.venvs/groundfault/bin/python` (Windows: `$HOME\.venvs\groundfault\Scripts\python.exe`) always means this
    environment – no other Python on the computer (a system Python, Homebrew, conda) can get in the way. Activating
    the environment (`source ~/.venvs/groundfault/bin/activate`, Windows
    `& $HOME\.venvs\groundfault\Scripts\Activate.ps1`) works as well.

**Updating.** In the clone, `git pull` is enough – the editable installation uses the new source at once; repeat the
`uv pip install` command only if the dependencies in `pyproject.toml` changed, and restart running Jupyter kernels.
An installation from the GitHub URL is updated by running the same `uv pip install` command again (uv resolves the
branch to its newest commit); with pip use `pip install --force-reinstall --no-deps "groundfault[all] @ git+https://github.com/Ce1ectric/groundfault"`
(with the extra you installed), because pip keeps an installed package with an unchanged version number.

## Jupyter: kernel, JupyterLab and VS Code

The notebooks are not part of the installed package; they are in the repository: `notebooks/en/`
(`evaluate_measurement.ipynb`, `evaluate_campaign.ipynb` and the reference copies in `templates/`) and
`notebooks/de/` (German). Copy them into your work folder as described in [Notebooks](../user-guide/notebooks.md).

**Register a kernel** once per environment (step 4 above; `python` is the Python of the environment):

```bash
python -m ipykernel install --user --name groundfault --display-name "Python (groundfault)"
```

**JupyterLab** – start it from the work folder (it is part of the `notebook` extra):

=== "macOS / Linux"

    ```bash
    cd <work folder>
    ~/.venvs/groundfault/bin/jupyter lab
    ```

=== "Windows (PowerShell)"

    ```powershell
    cd <work folder>
    & $HOME\.venvs\groundfault\Scripts\jupyter.exe lab
    ```

JupyterLab opens in the browser. Open a notebook and choose the kernel **Python (groundfault)** (menu *Kernel → Change
Kernel*).

**VS Code** – install the Jupyter extension, open the work folder, open a notebook and select the kernel
**Python (groundfault)** (or the Python interpreter of the environment) with *Select Kernel* in the top right corner.

If the signal explorer shows only an overview without controls, or interactive figures stay empty, see
[Troubleshooting](../user-guide/troubleshooting.md#installation-and-notebooks).

## Running the tests

The test suite checks every numerical method against a known synthetic solution or a second method (see
[Validation](../methods/validation.md)). In the clone, with the `dev` extra installed:

```bash
pytest -q
```

```text
…
SKIPPED [1] tests/test_units.py:63: could not import 'groundmeas.core.units': No module named 'groundmeas'
769 passed, 1 skipped in 371.05s (0:06:11)
```

It takes a few minutes. `pytest -k station` runs a subset. The skipped test compares the unit handling directly with
groundmeas; it runs when groundmeas 1.6.1 or newer is installed. That version is only available on GitHub and needs
Python 3.14 or newer – the version on PyPI is older and has no `groundmeas.core.units`:

```bash
pip install "groundmeas @ git+https://github.com/Ce1ectric/groundmeas@v1.6.1"
```

groundfault itself never needs groundmeas: it reads the database with the Python standard library and reproduces the
unit rules of groundmeas 1.6.1 (see [below](#the-groundmeas-database-optional)).

The code is checked with ruff; its rules, including the exceptions for the generated notebooks, are in
`pyproject.toml`:

```bash
ruff check
```

```text
All checks passed!
```

The continuous integration (`.github/workflows/`) runs the same two commands on the platforms and Python versions
above (with groundmeas 1.6.1 for the cross-check on Python 3.14 under Linux), the tests once more after
`uv pip install --resolution lowest-direct -e ".[dev]"` – the lowest declared version of every direct dependency – on
Python 3.10, and the strict documentation build.

## Building the documentation

With the `docs` extra installed (`pip install -e ".[docs]"`), in the clone:

```bash
mkdocs serve           # live preview on http://127.0.0.1:8000
mkdocs build --strict  # static site in site/, stops on every warning
```

The API reference is generated from the docstrings of the package. The figures in `docs/assets/` come from the demo
campaign and are regenerated with `python docs/scripts/make_figures.py`.

## The groundmeas database (optional)

The comparison of a station with its earthing measurements, the reduction factor and the entry of evaluated tests use
a groundmeas database (an SQLite file). groundfault reads it with the Python standard library and finds it as
groundmeas finds it:

1. the environment variable `GROUNDMEAS_DB`, otherwise
2. the entry `db_path` in `~/.config/groundmeas/config.json`, e.g. `{"db_path": "~/groundmeas/groundmeas.db"}`
   (Windows: `C:\Users\<name>\.config\groundmeas\config.json`).

Check which file is found:

```bash
python -c "from groundfault import earthing; print(earthing.default_db_path())"
```

`None` means that neither is set. Set the variable for one terminal session with `export GROUNDMEAS_DB=…`
(PowerShell: `$env:GROUNDMEAS_DB = "…"`) or permanently in your shell profile (Windows: `setx GROUNDMEAS_DB "…"`, then
open a new terminal). In the notebooks, `GROUNDMEAS_DB = "…"` overrides both; the example notebooks use the demo
database `demo_groundmeas.db`. Details: [Earthing measurements](../user-guide/earthing.md#where-the-database-is).
