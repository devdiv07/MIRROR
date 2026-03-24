import subprocess
import sys

print("=" * 70)
print("MIRROR - FULL PIPELINE EXECUTION")
print("=" * 70)

scripts = [
    ('SEC_INSIDER.PY', 'Collecting insider filings from SEC...'),
    ('NEWS_SENTIMENT.PY', 'Analyzing news sentiment...'),
    ('price_signal.py', 'Collecting price signals...'),
    ('dissonance_calculator.py', 'Calculating cognitive dissonance...')
]

for script, description in scripts:
    print(f"\n{'='*70}")
    print(description)
    print('='*70)
    
    result = subprocess.run([sys.executable, script])
    
    if result.returncode != 0:
        print(f"\n⚠ ERROR: {script} failed")
        sys.exit(1)

print("\n" + "="*70)
print("✓ MIRROR PIPELINE COMPLETE")
print("="*70)
