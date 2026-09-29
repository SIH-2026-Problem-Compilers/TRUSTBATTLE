# Schema / Interface Change Requests

> Add new requests at the bottom. Status: `PROPOSED → APPROVED / REJECTED`.
> Do NOT merge code that depends on an unapproved change.

---

| # | Date | Proposed by | Change | Reason | Status |
|---|------|-------------|--------|--------|--------|
| 1 | 2026-09-29 | M1 (physical) | Add additive `physical:` section to configs/settings.yaml (historical max speed, check limits, IF/OCSVM hyperparams, FPR target) | M1 tunables must live in the shared config per conventions; purely additive — no existing key touched, other members unaffected. Already shipped in commit b4c64a2 so M1 is testable; happy to restructure on request | PROPOSED |
