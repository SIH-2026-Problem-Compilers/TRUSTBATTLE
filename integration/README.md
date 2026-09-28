# integration/ — Shared Adapters

This folder is the **only** place where member modules connect.

| File | Purpose |
|---|---|
| `interfaces.py` | Approved function signatures (from `docs/contracts/module_interfaces.md`) + registry. Stubs raise `ModuleNotReadyError` until the owner ships. |
| `pipeline.py` | Registers whatever implementations exist, exposes `run_observation(window) -> full JSON message`. |
| `run_demo.py` | End-to-end demo runner: `python integration/run_demo.py` |

## How members plug in

1. Implement your function in **your own folder** with the exact contract signature.
2. Add your import to `register_available_implementations()` in `integration/pipeline.py`.
3. Never import another member's folder directly from your own code — go through `integration/interfaces.py`.

## Who may edit this folder

Edits here affect everyone: keep them minimal and announce them in the team chat.
Signature changes require an approved entry in `docs/contracts/CHANGE_REQUESTS.md`.
