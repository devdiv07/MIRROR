# SEC submissions fixtures (synthetic)

Shaped like `https://data.sec.gov/submissions/CIK##########.json`: filings in columnar arrays under
`filings.recent`, older filings in additional files listed in `filings.files` (same columnar
fields at the top level). The shape was checked against Apple's real submissions JSON
(CIK 0000320193) on 2026-09-23. Companies, CIKs and accession numbers here are invented.

| File | Used for |
|---|---|
| `CIK0000001234.json` | One CIK for two watched listings (C7); an 8-K inside the window (C6); an S-8 that is ignored |
| `CIK0000005678.json` | Nothing inside the window (C5) |
| `CIK0000004242.json` + `-submissions-001.json` | `recent` starts 2026-01-05 and an older file holds 2025-06-01..2026-01-05 (B1) |

`acceptanceDateTime` values end in `Z` and are UTC (ADR 0001 §14, Q3).
