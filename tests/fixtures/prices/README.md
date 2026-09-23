# Price CSV fixtures (synthetic)

MIRROR's price file format (see `src/sources/prices_csv.py`): optional `# vendor:`, `# source_url:` and `# as_of:` declarations, then `security_key,trade_date,open,high,low,close,volume,adj_close`. The securities are the invented ones in `tests/support.py`. The prices are made up.

| File | Used for |
|---|---|
| `us_unknown_upstream.csv` | No declarations, so the upstream source is "unknown" (case P1) |
| `us_declared_vendor.csv` | A declared vendor, link and vendor as-of time; adj_close for the cross-check |

Longer series (20+ sessions for the volume ratio, split/bonus days) are generated in the tests, which keeps each case's numbers next to its assertions.
