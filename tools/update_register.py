# -*- coding: utf-8 -*-
"""Update the register, the read-me files and the notes folders of all campaigns of a work folder.

Usage::

    python tools/update_register.py [WORK_FOLDER] [--layout en|de] [--lang en|de]

The work folder contains the campaigns folder (``campaigns`` or ``01_Messkampagnen``); default: the current folder.
Columns of the register maintained by hand (fault resistance, fault location, remark, intervals) are kept. Messages
are printed in the language of the folder layout unless ``--lang`` gives another one.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))          # run from a clone without installing

from groundfault import i18n, register  # noqa: E402
from groundfault.i18n import tr  # noqa: E402
from groundfault.layout import detect_layout, get_layout  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("work_folder", nargs="?", default=".", help="folder that contains the campaigns folder")
    ap.add_argument("--layout", choices=("en", "de"), default=None, help="folder layout (default: detected)")
    ap.add_argument("--lang", choices=("en", "de"), default=None,
                    help="language of the messages (default: the language of the folder layout)")
    a = ap.parse_args(argv)
    base = os.path.abspath(a.work_folder)
    lay = get_layout(a.layout) if a.layout else detect_layout(base)
    i18n.set_language(a.lang or lay.language)
    r = register.update_all(base, layout=lay)
    print(tr("register.summary_register", path=r["register"], count=r["files"]))
    print(tr("register.summary_readme", file=lay.readme_file, count=len(r["readme"])))
    for x in r["actions"]:
        print("•", x)
    for h in r["hints"]:
        print("⚠", h)


if __name__ == "__main__":
    main()
