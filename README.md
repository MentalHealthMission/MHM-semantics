# MHM Semantics

Python semantic runtime for ODIM-MH/MHM pipeline use.

This repository contains ontology loading, namespace configuration, feature
selection, unification, reasoning, semantic planning, and derived-feature
metadata helpers. The base ontology assets remain in
`MentalHealthMission/MHM-ontology`.

## What This Package Owns

- ontology loading and cache helpers
- configurable namespace handling
- feature and rule catalogues
- semantic unification and reasoning helpers
- derived-feature metadata generation
- semantic run-spec planning primitives

## Install

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e .
python scripts/check_semantic_package_contract.py
```
