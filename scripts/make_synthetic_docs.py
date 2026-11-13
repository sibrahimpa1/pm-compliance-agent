"""Regenerate the synthetic PDFs in data/docs/ and their offline fixtures.

    python scripts/make_synthetic_docs.py

Output is deterministic: running it twice gives byte-identical files.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pmcompliance.synthetic import build_all  # noqa: E402

if __name__ == "__main__":
    for relpath, sha in build_all(ROOT):
        print("%-34s %s" % (relpath, sha[:12]))
