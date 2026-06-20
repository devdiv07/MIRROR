## What does this PR do?

<!-- One sentence. What changes and why. -->

## Type of change

- [ ] `fix:` Bug fix
- [ ] `feat:` New scorer / enrichment / CLI feature
- [ ] `test:` Test additions or fixes
- [ ] `docs:` Documentation only
- [ ] `chore:` CI, deps, config
- [ ] `security:` Security fix
- [ ] `refactor:` No behavior change

## Files changed

<!-- List the files modified and why. -->

## Testing

- [ ] `pytest tests/ -v` passes locally
- [ ] New behavior is covered by at least one test
- [ ] Edge cases (None, NaN, missing columns) are handled
- [ ] No new bare `except:` blocks introduced

## Security checklist

- [ ] No secrets, API keys, or .env content in this diff
- [ ] No new dependency added without justification in this description
- [ ] If XML parsing is touched: defusedxml is used, not xml.etree
- [ ] All new `requests.get()` calls include `timeout=`

## Docs

- [ ] `docs/` updated if behavior changed
- [ ] YAML config updated if new scorer added
- [ ] No speculative doc changes (only update what actually changed)
