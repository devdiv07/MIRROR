"""
Tests for Fix 3: entity filer tagging in parser + aggregator gate.
Run from insider_signal_phase1/ directory.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.parsers.insider_parser_v2 import parse_form4_xml
from src.scoring.aggregator import aggregate
from src.scoring import conviction, role, market_cap, liquidity, cluster, routine_penalty, tenb_penalty  # noqa: F401


# ── Parser tests ─────────────────────────────────────────────────────────────

def test_entity_filer_tagged_in_parser():
    """isCompany=1 in XML → is_company=True in output row."""
    xml = """<ownershipDocument>
      <rptOwnerName>GOLDMAN SACHS GROUP INC</rptOwnerName>
      <reportingOwner>
        <reportingOwnerType><isCompany>1</isCompany></reportingOwnerType>
        <reportingOwnerRelationship><isOther>1</isOther></reportingOwnerRelationship>
      </reportingOwner>
      <nonDerivativeTable>
        <nonDerivativeTransaction>
          <transactionCode>P</transactionCode>
          <transactionDate><value>2026-01-15</value></transactionDate>
          <transactionShares><value>566000</value></transactionShares>
          <transactionPricePerShare><value>5.69</value></transactionPricePerShare>
          <sharesOwnedFollowingTransaction><value>600000</value></sharesOwnedFollowingTransaction>
        </nonDerivativeTransaction>
      </nonDerivativeTable>
    </ownershipDocument>"""

    rows = parse_form4_xml(xml, 'GS', '2026-01-16')
    assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"
    assert rows[0]['is_company'] is True, f"Expected is_company=True, got {rows[0]['is_company']}"
    print(f"  PASS: entity filer tagged as is_company=True")


def test_human_filer_not_tagged():
    """isCompany=0 (or absent) → is_company=False."""
    xml = """<ownershipDocument>
      <rptOwnerName>DIMON JAMES</rptOwnerName>
      <reportingOwner>
        <reportingOwnerType><isCompany>0</isCompany></reportingOwnerType>
        <reportingOwnerRelationship>
          <isOfficer>1</isOfficer>
        </reportingOwnerRelationship>
      </reportingOwner>
      <nonDerivativeTable>
        <nonDerivativeTransaction>
          <transactionCode>S</transactionCode>
          <transactionDate><value>2026-01-15</value></transactionDate>
          <transactionShares><value>10000</value></transactionShares>
          <transactionPricePerShare><value>250.00</value></transactionPricePerShare>
          <sharesOwnedFollowingTransaction><value>500000</value></sharesOwnedFollowingTransaction>
        </nonDerivativeTransaction>
      </nonDerivativeTable>
    </ownershipDocument>"""

    rows = parse_form4_xml(xml, 'JPM', '2026-01-16')
    assert len(rows) == 1
    assert rows[0]['is_company'] is False, f"Expected is_company=False, got {rows[0]['is_company']}"
    print(f"  PASS: human filer tagged as is_company=False")


# ── Aggregator gate tests ─────────────────────────────────────────────────────

def test_aggregator_gates_entity_filer():
    """aggregate() returns 0.0 immediately for is_company=True rows."""
    row = {
        'is_company': True,
        'transaction_type': 'BUY',
        'pct_holdings_transacted': 0.9,
        'is_routine_insider': False,
        'title': 'CEO',
        'dollar_value': 3_200_000,
        'market_cap': None,
        'avg_30d_dollar_volume': None,
        'ticker': 'GS',
        'date': '2026-01-15',
        'insider_name': 'GOLDMAN SACHS GROUP INC',
    }
    result = aggregate(row)
    assert result == 0.0, f"Expected 0.0 for entity filer, got {result}"
    print(f"  PASS: entity filer gated → signal = 0.0")


def test_aggregator_does_not_gate_human():
    """aggregate() does NOT zero-out human insider rows."""
    row = {
        'is_company': False,
        'transaction_type': 'BUY',
        'pct_holdings_transacted': 0.5,
        'is_routine_insider': False,
        'is_10b51_plan': False,
        'title': 'Chief Executive Officer',
        'dollar_value': 1_000_000,
        'market_cap': None,
        'avg_30d_dollar_volume': None,
        'ticker': 'JPM',
        'date': '2026-01-15',
        'insider_name': 'DIMON JAMES',
    }
    result = aggregate(row)
    assert result != 0.0, f"Expected non-zero for human insider, got {result}"
    assert result > 0.0, f"Expected positive BUY signal, got {result}"
    print(f"  PASS: human insider not gated → signal = {result:.4f}")


if __name__ == '__main__':
    print("=" * 60)
    print("FIX 3: ENTITY FILER TAGGING TESTS")
    print("=" * 60)
    tests = [
        test_entity_filer_tagged_in_parser,
        test_human_filer_not_tagged,
        test_aggregator_gates_entity_filer,
        test_aggregator_does_not_gate_human,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print()
    print(f"Results: {passed} passed, {failed} failed")
