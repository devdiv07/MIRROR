"""Quick check: confirm registry enabled flags after fix."""
import sys
sys.path.insert(0, '.')

from scoring import conviction, role, market_cap, liquidity, cluster, routine_penalty, tenb_penalty
from scoring.registry import SCORER_REGISTRY

print('Scorer registry enabled status:')
for name, cfg in SCORER_REGISTRY.items():
    w = cfg['weight']
    e = cfg['enabled']
    print(f'  {name:<25}  weight={w:6.2f}  enabled={e}')

# The test: negative-weight scorers must be enabled
assert SCORER_REGISTRY['routine_penalty']['enabled'], "routine_penalty still disabled!"
assert SCORER_REGISTRY['tenb_penalty']['enabled'],   "tenb_penalty still disabled!"
print()
print("PASS: routine_penalty and tenb_penalty are now enabled.")
