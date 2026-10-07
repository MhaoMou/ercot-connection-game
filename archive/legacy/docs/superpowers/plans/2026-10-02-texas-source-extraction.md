# Texas Source Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a deterministic, ZIP-streaming extraction and validation tool for the 2,000-bus Texas interconnect in Zenodo 4538590.

**Architecture:** A focused standard-library Python module reads the archive, filters network tables by `interconnect == Texas`, validates identifiers and boundary records, and writes canonical CSVs plus a JSON report containing counts, profile coverage, and SHA-256 hashes. It deliberately does not modify the evaluator or decide the final student-visible candidate-site layer.

**Tech Stack:** Python 3.11+, standard library `zipfile`, `csv`, `hashlib`, `argparse`, and pytest.

---

### Task 1: Define extraction and validation behavior with tests

**Files:**
- Create: `tests/test_zenodo_texas_extraction.py`

- [x] Test that a fixture ZIP extracts only rows whose `interconnect` is `Texas` and preserves CSV headers.
- [x] Test that branch endpoints, bus-to-substation references, plant bus references, and gencost plant references are reported as unresolved when malformed.
- [x] Test that a profile table reports its timestamp column and the number of columns that match selected bus or plant IDs; profile columns with no mapping are diagnostics, not silent claims of coverage.
- [x] Test that the output report contains deterministic SHA-256 hashes and stable sorted file names.

### Task 2: Implement the ZIP-streaming extractor

**Files:**
- Create: `tools/zenodo_texas/extract.py`
- Create: `tools/zenodo_texas/__init__.py`

- [x] Implement `extract_archive(archive, output_dir)` using the exact `interconnect == Texas` selector.
- [x] Extract network CSVs and preserve source column order.
- [x] Validate referential integrity and record errors/warnings without changing source values.
- [x] Inspect profile headers and write only profiles whose column semantics can be resolved; record unresolved profile coverage explicitly.
- [x] Write `manifest.json` with source archive metadata, selection rule, row counts, diagnostics, and SHA-256 hashes.
- [x] Add a CLI with explicit archive and output arguments.

### Task 3: Run against the Zenodo archive and document findings

**Files:**
- Create: `data/processed/texas_dispatch_source_v1/`
- Modify: `docs/ERCOT_CONNECTION_PLANNING_GAME_CONCRETE_PLAN.md`
- Modify: `data/intermediate/source_manifest_zenodo_4538590.json`

- [x] Run the extractor on `data/raw/USATestSystem.zip`.
- [x] Verify the expected 2,000 Texas buses, 3,206 branches, 1,250 substations, and 598 plants.
- [x] Record profile-column semantics and the two boundary/DC-tie findings.
- [x] Resolve zonal demand and plant-profile semantics; retain only Texas-relevant profile columns rather than fabricating bus-level profiles.

### Task 4: Verification

- [x] Run the focused extraction tests (`5 passed`).
- [x] Run the full existing test suite (`608 passed`).
- [x] Parse the generated JSON manifest and verify all reported hashes against output files.

### Follow-up: Dispatch preparation completed

The extracted artifact was extended with `demand_bus.csv`,
`generator_limits.csv`, `branch_limits.csv`, and `dispatch_manifest.json`.
The next independent implementation plan should cover the dispatch formulation
and its small benchmark network; this extraction plan is complete.
