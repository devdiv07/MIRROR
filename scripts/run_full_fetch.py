"""
run_full_fetch.py — fetch Form 4 filings for the full small/mid-cap universe.

Saves to data/insider_filings.csv (overwrites the old mega-cap file).
The old file is backed up to data/insider_filings_megacap_backup.csv first.
"""
import sys, os, shutil
sys.path.insert(0, os.path.abspath('.'))

from src.parsers.sec_filings_fetcher import collect_all_insider_filings

# Back up the old mega-cap baseline before overwriting
src_path = 'data/insider_filings.csv'
bak_path = 'data/insider_filings_megacap_backup.csv'
if os.path.exists(src_path) and not os.path.exists(bak_path):
    shutil.copy(src_path, bak_path)
    print(f"Backed up old filings to {bak_path}")

df = collect_all_insider_filings()
print(f"\nDone. {len(df)} filings ready for parsing.")
print("Next: python -m src.parsers.insider_parser_v2")
