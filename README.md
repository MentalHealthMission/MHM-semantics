# MHM Semantics

Python tools for working with ODIM-MH/MHM semantic assets.

Use this package to load ontology assets, configure namespaces, select
features, resolve semantic mappings, run lightweight reasoning helpers, and
generate derived-feature metadata.

The base ontology assets are maintained in `MentalHealthMission/MHM-ontology`.

## What You Can Do

- load and cache ontology files
- configure namespace aliases
- inspect feature and rule catalogues
- unify semantic feature definitions
- generate derived-feature metadata
- build semantic run specifications

## Install

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e .
python scripts/check_semantic_package_contract.py
```
