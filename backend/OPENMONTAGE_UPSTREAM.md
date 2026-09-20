# OpenMontage upstream

| | |
|---|---|
| Repository | https://github.com/calesthio/OpenMontage |
| Commit SHA | `08e2151fa02de28a5d6a312b3d575692bf147ad7` |
| Commit date | 2026-09-05 (Sat Sep 5 22:02:12 2026 -0700) |
| Imported | 2026-09-20 (shallow clone, `.git` removed) |
| License | GNU AGPL-3.0 - see `openmontage/LICENSE` (unmodified) |

The engine lives in `backend/openmontage/` and is used as an internal library/runtime only.
No OpenMontage terminology, paths or provider names are exposed through the public API.

## Local modifications

Everything else under `backend/openmontage/` is byte-for-byte upstream.

1. **Added** `openmontage/pipeline_defs/app-cinematic.yaml` - a headless consumer-app pipeline
   derived from upstream `cinematic.yaml`. It reuses the upstream `pipelines/cinematic/*`
   director skills and tools unchanged. Differences: every stage has
   `human_approval_default: false` (no approval is ever faked - the gates simply do not exist in this
   pipeline), the human-facing `publish` stage is dropped, research is capped, `custom_*` extensions
   are off. Schema validation, self-review, checkpoints, cost governance and render verification are kept.
   The upstream contract suite (`tests/contracts/test_pipeline_catalog.py`) validates this manifest.

2. **Added** best-take selection (all new files, no upstream file modified):
   - `openmontage/lib/take_selection.py` - stdlib-only engine: word-level transcript -> utterances -> repeated-take groups
     -> scores -> edit decision list (dead air, fillers, off-script talk removed)
   - `openmontage/tools/analysis/take_analyzer.py` - registry tool `take_analyzer` (`analyze`, `edl`)
   - `openmontage/.agents/skills/take-selection/SKILL.md` - Layer 3 skill so agents know how to use it

No other file was changed. When updating the engine, re-import upstream over `backend/openmontage/`,
re-apply item 1, update the SHA above, and run `make test-contracts` inside `backend/openmontage/`.

## Upstream contract tests

`make test-contracts` (equivalently `python -m pytest tests/contracts`) at the imported SHA with the
local modification above: **1215 passed, 7 skipped** (skips are upstream's own conditional skips).
