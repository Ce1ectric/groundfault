# -*- coding: utf-8 -*-
"""Public API: every module lists existing names in ``__all__``, and the public names that the documentation pages
(``module.NAME``) or the cross-references of the docstrings (``[`NAME`][groundfault.module.NAME]``) refer to are in
``__all__`` – the API reference shows exactly these names; the docstrings use no Sphinx roles. The version is the same
in every file that states it."""
import ast
import glob
import importlib
import os
import re

import pytest

from groundfault import i18n

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULES = sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(ROOT, "src", "groundfault",
                                                                                          "*.py"))
                 if not p.endswith("__init__.py"))


@pytest.mark.parametrize("name", MODULES)
def test_all_lists_existing_names(name):
    module = importlib.import_module("groundfault." + name)
    assert module.__all__ and all(hasattr(module, n) for n in module.__all__)


def test_names_in_the_documentation_are_public():
    pattern = re.compile(r"(?<![\w.\"'/])(?:groundfault\.)?(%s)\.([A-Za-z]\w*)(?!\.md)" % "|".join(MODULES))
    missing = set()
    for path in glob.glob(os.path.join(ROOT, "docs", "**", "*.md"), recursive=True):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for module_name, name in pattern.findall(text):
            module = importlib.import_module("groundfault." + module_name)
            if hasattr(module, name) and not i18n.has_message("%s.%s" % (module_name, name)) \
                    and not isinstance(getattr(module, name), type(module)) and name not in module.__all__:
                missing.add("%s.%s (%s)" % (module_name, name, os.path.relpath(path, ROOT)))
    assert not missing


def _public(identifier):
    """True if ``groundfault.<module>[.<name>[.<member>]]`` is a module, a name in the ``__all__`` of its module or a
    member of such a class."""
    parts = identifier.split(".")
    obj = importlib.import_module(parts[0])
    for i, part in enumerate(parts[1:], 1):
        if isinstance(obj, type(os)):
            if part in MODULES and i == 1:
                obj = importlib.import_module("groundfault." + part)
                continue
            if part not in obj.__all__:
                return False
        if not hasattr(obj, part):
            return False
        obj = getattr(obj, part)
    return True


@pytest.mark.parametrize("name", MODULES + ["__init__"])
def test_cross_references_of_the_docstrings_point_to_public_names(name):
    """The docstrings refer to other objects with Markdown cross-references that mkdocstrings resolves
    (``[`table`][groundfault.evaluation.Result.table]``), not with Sphinx roles (``:func:`…```), which the API
    reference would show literally; every target is public."""
    module = importlib.import_module("groundfault" if name == "__init__" else "groundfault." + name)
    with open(module.__file__, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    docs = [n.value.value for n in ast.walk(tree) if isinstance(n, ast.Expr)
            and isinstance(getattr(n, "value", None), ast.Constant) and isinstance(n.value.value, str)]
    roles = [m.group(0) for d in docs for m in re.finditer(r":(?:func|class|data|mod|meth|attr|exc|obj):`[^`]+`", d)]
    assert roles == []
    targets = {t for d in docs for t in re.findall(r"\]\[(groundfault(?:\.\w+)*)\]", d)}
    assert {t for t in targets if not _public(t)} == set()


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def test_version_is_the_same_everywhere():
    """The version in pyproject.toml, ``groundfault.__version__``, CITATION.cff, the BibTeX entry of the README, the
    top entry of CHANGELOG.md and the printed version in the installation and quickstart pages agree; the date of the
    top changelog entry is the release date in CITATION.cff."""
    import groundfault
    project = re.search(r"^\[project\]\n(.*?)(?=^\[)", _read("pyproject.toml"), re.M | re.S).group(1)
    citation = _read("CITATION.cff")
    bibtex = re.search(r"```bibtex\n(.*?)```", _read("README.md"), re.S).group(1)
    top = re.search(r"^## \[([^\]]+)\] - (\d{4}-\d{2}-\d{2})$", _read("CHANGELOG.md"), re.M)
    versions = {
        "pyproject.toml": re.search(r'^version = "([^"]+)"$', project, re.M).group(1),
        "groundfault.__version__": groundfault.__version__,
        "CITATION.cff": re.search(r'^version: "?([^"\n]+?)"?$', citation, re.M).group(1),
        "README.md (BibTeX)": re.search(r"version\s*=\s*\{([^}]+)\}", bibtex).group(1),
        "CHANGELOG.md (top entry)": top.group(1),
        "installation.md": re.search(r"print\(groundfault.__version__\)\"\n```\n\n```text\n(\S+)\n",
                                     _read("docs/getting-started/installation.md")).group(1),
        "quickstart.md": re.search(r"^groundfault (\S+) · ", _read("docs/getting-started/quickstart.md"),
                                   re.M).group(1),
    }
    assert len(set(versions.values())) == 1, versions
    assert re.search(r'^date-released: "?%s"?$' % top.group(2), citation, re.M), "CITATION.cff date-released"
