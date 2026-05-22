# MHM Semantics

Python semantic runtime for ODIM-MH/MHM pipeline use.

This repository contains ontology loading, namespace configuration, feature
selection, unification, reasoning, semantic planning, and derived-feature
metadata helpers. The base ontology assets remain in
`MentalHealthMission/MHM-ontology`; CONNECT extensions remain in CONNECT
repositories.

## Install

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e .
python scripts/check_semantic_package_contract.py
```

This branch was extracted from
`connect-summary@011391223d0acaa28eb4c19ad5cd3e8f3e022d0b`.
