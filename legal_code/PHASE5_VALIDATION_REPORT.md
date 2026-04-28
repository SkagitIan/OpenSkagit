# Phase 5 Validation Report

Run date: February 10, 2026

## Scope
Validated Phase 5 requirements:
1. All 7 jurisdictions have non-zero legal section coverage in DB.
2. `GET /agent/legal/search/` and `GET /agent/legal/get/` smoke checks pass for each jurisdiction.
3. Endpoint and command tests pass.

## Coverage Counts (latest section revisions)
Generated via DB adapter coverage query and `manage.py validate_legal_phase5 --fail-on-error`.

| Jurisdiction | Count |
|---|---:|
| sedro_woolley | 1599 |
| mount_vernon | 936 |
| la_conner | 796 |
| skagit_county | 1455 |
| anacortes | 1772 |
| burlington | 1964 |
| washington_state | 47 |

## Smoke Checks
Command:

```bash
python3 manage.py validate_legal_phase5 --fail-on-error
```

Result: 7/7 jurisdictions passed.

Sample IDs validated by `search -> get`:
1. `sedro_woolley`: `cp:sedro_woolley:eyJjIjoiMTguNDUiLCJkIjoiQUxMIiwicyI6IjE4LjQ1LjAzMCJ9`
2. `mount_vernon`: `cp:mount_vernon:eyJjIjoiMTcuMjEwIiwiZCI6IkFMTCIsInMiOiIxNy4yMTAuMDcwIn0`
3. `la_conner`: `cp:la_conner:eyJjIjoiMTUuMTUwIiwiZCI6IkFMTCIsInMiOiIxNS4xNTAuMDMwIn0`
4. `skagit_county`: `cp:skagit_county:eyJjIjoiMTYuMzIiLCJkIjoiQUxMIiwicyI6IjE2LjMyLjE2MCJ9`
5. `anacortes`: `mc:anacortes:eyJjIjoiMjAuMzAiLCJkIjoiQUxMIiwicyI6IjIwLjMwLjE0MCJ9`
6. `burlington`: `ec:burlington:eyJjIjoiMTguMTYiLCJkIjoiQUxMIiwicyI6IjIuMDQifQ`
7. `washington_state`: `wa:washington_state:eyJjIjoiMzA4LTE3IiwiZCI6IldBQyIsInMiOiIzMDgtMTctMTkwIn0`

## Tests
Commands and results:

```bash
python3 manage.py test mcp_agent.tests
python3 manage.py test legal_code.tests
```

Both suites passed in this run.

