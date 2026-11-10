"""`_legacy/` is reference-only (see README.md in this folder) -- it is
not deployed and its colocated `test.py`/`integration.py` files test
ORM shapes and modules that no longer exist. Tell pytest to skip this
whole subtree instead of letting collection fail.
"""

collect_ignore_glob = ["*"]
