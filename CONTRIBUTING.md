# Contributing to groundfault

Thank you for helping to improve groundfault. This file describes how the code is organised and the conventions
for code, documentation, messages and tests.

## Development set-up

```bash
git clone https://github.com/Ce1ectric/groundfault.git
cd groundfault
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev,docs]"
pytest
ruff check                                             # rules in pyproject.toml
mkdocs serve                                           # documentation on http://127.0.0.1:8000
```

## Conventions

### Language

* **Code, identifiers, docstrings, comments, commit messages and documentation are in English.**
* User-facing output (hints, warnings, error messages, plausibility checks, table and figure labels, exported
  files) is available in **English and German**. It is rendered from message catalogs with
  `groundfault.i18n.tr()`; tables are translated for display with `groundfault.i18n.localize()`.
* Internally everything uses English names: table columns (`U_E_fault_V`), codes (`"satisfied"`, `"below"`),
  roles (`i_res`, `u_e`), parameters and dictionary keys. German names only appear in the German message texts,
  in `i18n.COLUMNS_DE`/`VALUES_DE` (display), in the German folder layout and the German headers of the campaign
  files (`layout`, `corrections`, `sites`, `register`) and in `legacy` (reading files of the predecessor tool).

### Messages (i18n)

Every module that produces user-facing text registers its messages once at import:

```python
from . import i18n
from .i18n import tr

i18n.register({
    "evaluation.angle_atypical": {
        "en": "Angle U_E/I_F ({channel}, 50 Hz) = {angle:.0f}° – atypical for an earthing impedance …",
        "de": "Winkel U_E/I_F ({channel}, 50 Hz) = {angle:.0f}° – für eine Erdungsimpedanz untypisch …",
    },
})

res.hints.append(tr("evaluation.angle_atypical", channel=k.short, angle=phi))
```

* Keys are `"<module>.<short_name>"` (lower case, underscores).
* Templates use `str.format` fields with names (`{channel}`, `{value:.2f}`); numbers are formatted with a decimal
  comma (and a full stop as thousands separator) in German automatically.
* Table cells hold language-neutral codes (`"satisfied"`, `"touch_voltage"`); their German display texts live in
  `i18n.VALUES_DE`, German column names in `i18n.COLUMNS_DE`. Text that depends on the language never goes into a
  table cell that other code filters on.
* Both languages must be present; the test suite checks this (`i18n.missing_keys`).
* Exceptions (`ValueError`, …) also use `tr()`.

### Docstrings

NumPy style (rendered by mkdocstrings):

```python
def reduction_factor(tables, db_response, tolerance_hz=5.0):
    """Reduction factor from the staged fault test and the earthing measurement.

    Parameters
    ----------
    tables : Result or dict
        ...

    Returns
    -------
    spectrum, effective : pandas.DataFrame
        ...
    """
```

Public functions and classes get a full docstring (summary, parameters, returns, raises, notes or examples where
helpful); private helpers a one-line summary. The API reference shows every name in `__all__` that has a docstring:

* constants in `__all__` get an attribute docstring – a string literal right after the assignment; a `#:` comment is
  not shown;
* other objects are referred to with Markdown cross-references that mkdocstrings resolves, with the full path in the
  second brackets: ``[`load`][groundfault.corrections.load]``, ``[`table`][groundfault.evaluation.Result.table]``.
  Sphinx roles (`` :func:`load` ``) would appear literally. Private helpers and objects of other packages are written as
  inline code; the strict documentation build fails on a cross-reference it cannot resolve.

### Other

* Library code does not print: it returns its findings to the caller – as hints (`Result.hints`, the `hints` of an
  export plan …) and plausibility rows – or issues them with `warnings.warn`, always through `tr()`. Printing is left
  to the notebooks and the scripts in `tools/`.
* Every module defines `__all__`.
* The version is stated in `pyproject.toml`, `src/groundfault/__init__.py`, `CITATION.cff` (with the release date),
  the BibTeX entry of `README.md`, the top entry of `CHANGELOG.md` and the printed version on the installation and
  quickstart pages; a test checks that they agree.
* The notebooks in `notebooks/` are generated: change `tools/make_notebooks.py` and regenerate them with
  `python tools/make_notebooks.py --lang en --out notebooks/en --example --overwrite` (and the same with
  `--lang de --out notebooks/de`); a test checks that the committed notebooks are exactly the generator's output.
* Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`,
  `test:`, `refactor:`, `chore:`).
* No measurement data, network data, campaign configurations, logos or names of companies or persons in the
  repository. Tests use synthetic recordings (`groundfault.demo`) only.

## Tests

```bash
pytest                 # all tests (they check the German output; English is checked explicitly)
pytest -k station      # a subset
```

Every numerical method is checked against a second method or an exact synthetic solution
(`groundfault.demo` generates COMTRADE recordings with known truth). One test compares the unit handling directly
with groundmeas; it is skipped unless groundmeas 1.6.1 or newer is installed – only available on GitHub and for
Python 3.14 or newer: `pip install "groundmeas @ git+https://github.com/Ce1ectric/groundmeas@v1.6.1"`.

The suite must also pass with the lowest declared versions of the dependencies on Python 3.10, as the continuous
integration checks:

```bash
pip install uv
uv pip install --resolution lowest-direct -e ".[dev]"     # in a fresh Python 3.10 environment
pytest -q
```

and without ResourceWarnings: `pytest -q -W error::ResourceWarning` (open files with `with` or `pathlib`).
