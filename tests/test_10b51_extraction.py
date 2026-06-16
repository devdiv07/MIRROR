"""
Tests for Fix 4: aff10b5One and footnote extraction in insider_parser_v2.
Run from insider_signal_phase1/ directory.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.parsers.insider_parser_v2 import parse_form4_xml


# ── aff10b5One tests ──────────────────────────────────────────────────────────

def test_10b51_raw_extracted_when_present():
    """<aff10b5One>1</aff10b5One> → is_10b51_raw=1 in output."""
    xml = """<ownershipDocument>
      <rptOwnerName>TEST PERSON</rptOwnerName>
      <reportingOwner>
        <reportingOwnerType><isCompany>0</isCompany></reportingOwnerType>
        <reportingOwnerRelationship><isOfficer>1</isOfficer></reportingOwnerRelationship>
      </reportingOwner>
      <aff10b5One>1</aff10b5One>
      <nonDerivativeTable>
        <nonDerivativeTransaction>
          <transactionCode>S</transactionCode>
          <transactionDate><value>2026-01-15</value></transactionDate>
          <transactionShares><value>1000</value></transactionShares>
          <transactionPricePerShare><value>100.00</value></transactionPricePerShare>
          <sharesOwnedFollowingTransaction><value>5000</value></sharesOwnedFollowingTransaction>
        </nonDerivativeTransaction>
      </nonDerivativeTable>
    </ownershipDocument>"""

    rows = parse_form4_xml(xml, 'TEST', '2026-01-16')
    assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"
    assert 'is_10b51_raw' in rows[0], "is_10b51_raw missing from output"
    assert rows[0]['is_10b51_raw'] == 1, f"Expected 1, got {rows[0]['is_10b51_raw']}"
    print(f"  PASS: aff10b5One=1 → is_10b51_raw={rows[0]['is_10b51_raw']}")


def test_10b51_raw_none_when_absent():
    """No <aff10b5One> in XML → is_10b51_raw=None (pre-2023 filing)."""
    xml = """<ownershipDocument>
      <rptOwnerName>TEST PERSON</rptOwnerName>
      <reportingOwner>
        <reportingOwnerType><isCompany>0</isCompany></reportingOwnerType>
        <reportingOwnerRelationship><isOfficer>1</isOfficer></reportingOwnerRelationship>
      </reportingOwner>
      <nonDerivativeTable>
        <nonDerivativeTransaction>
          <transactionCode>P</transactionCode>
          <transactionDate><value>2022-06-01</value></transactionDate>
          <transactionShares><value>5000</value></transactionShares>
          <transactionPricePerShare><value>150.00</value></transactionPricePerShare>
          <sharesOwnedFollowingTransaction><value>20000</value></sharesOwnedFollowingTransaction>
        </nonDerivativeTransaction>
      </nonDerivativeTable>
    </ownershipDocument>"""

    rows = parse_form4_xml(xml, 'TEST', '2022-06-02')
    assert len(rows) == 1
    assert rows[0]['is_10b51_raw'] is None, f"Expected None, got {rows[0]['is_10b51_raw']}"
    print(f"  PASS: no aff10b5One → is_10b51_raw=None")


def test_10b51_raw_zero_when_not_plan():
    """<aff10b5One>0</aff10b5One> → is_10b51_raw=0 (explicitly NOT a plan trade)."""
    xml = """<ownershipDocument>
      <rptOwnerName>TEST PERSON</rptOwnerName>
      <reportingOwner>
        <reportingOwnerType><isCompany>0</isCompany></reportingOwnerType>
        <reportingOwnerRelationship><isOfficer>1</isOfficer></reportingOwnerRelationship>
      </reportingOwner>
      <aff10b5One>0</aff10b5One>
      <nonDerivativeTable>
        <nonDerivativeTransaction>
          <transactionCode>S</transactionCode>
          <transactionDate><value>2026-01-15</value></transactionDate>
          <transactionShares><value>2000</value></transactionShares>
          <transactionPricePerShare><value>100.00</value></transactionPricePerShare>
          <sharesOwnedFollowingTransaction><value>8000</value></sharesOwnedFollowingTransaction>
        </nonDerivativeTransaction>
      </nonDerivativeTable>
    </ownershipDocument>"""

    rows = parse_form4_xml(xml, 'TEST', '2026-01-16')
    assert len(rows) == 1
    assert rows[0]['is_10b51_raw'] == 0, f"Expected 0, got {rows[0]['is_10b51_raw']}"
    print(f"  PASS: aff10b5One=0 → is_10b51_raw=0")


# ── footnote tests ────────────────────────────────────────────────────────────

def test_footnotes_extracted_and_concatenated():
    """Two footnotes concatenated with ' | '."""
    xml = """<ownershipDocument>
      <rptOwnerName>TEST PERSON</rptOwnerName>
      <reportingOwner>
        <reportingOwnerType><isCompany>0</isCompany></reportingOwnerType>
        <reportingOwnerRelationship><isOfficer>1</isOfficer></reportingOwnerRelationship>
      </reportingOwner>
      <nonDerivativeTable>
        <nonDerivativeTransaction>
          <transactionCode>S</transactionCode>
          <transactionDate><value>2026-01-15</value></transactionDate>
          <transactionShares><value>1000</value></transactionShares>
          <transactionPricePerShare><value>100.00</value></transactionPricePerShare>
          <sharesOwnedFollowingTransaction><value>5000</value></sharesOwnedFollowingTransaction>
        </nonDerivativeTransaction>
      </nonDerivativeTable>
      <footnotes>
        <footnote id="F1">This sale was made pursuant to a Rule 10b5-1 plan.</footnote>
        <footnote id="F2">Represents tax withholding only.</footnote>
      </footnotes>
    </ownershipDocument>"""

    rows = parse_form4_xml(xml, 'TEST', '2026-01-16')
    assert len(rows) == 1
    assert 'footnotes' in rows[0], "footnotes missing from output"
    fn = rows[0]['footnotes']
    assert fn is not None, "Expected footnote text, got None"
    assert '10b5-1 plan' in fn, f"Expected 10b5-1 language in footnotes, got: {fn}"
    assert ' | ' in fn, f"Expected ' | ' separator, got: {fn}"
    print(f"  PASS: footnotes extracted: '{fn[:60]}...'")


def test_footnotes_none_when_absent():
    """No <footnotes> block → footnotes=None."""
    xml = """<ownershipDocument>
      <rptOwnerName>TEST PERSON</rptOwnerName>
      <reportingOwner>
        <reportingOwnerType><isCompany>0</isCompany></reportingOwnerType>
        <reportingOwnerRelationship><isOfficer>1</isOfficer></reportingOwnerRelationship>
      </reportingOwner>
      <nonDerivativeTable>
        <nonDerivativeTransaction>
          <transactionCode>P</transactionCode>
          <transactionDate><value>2026-01-15</value></transactionDate>
          <transactionShares><value>1000</value></transactionShares>
          <transactionPricePerShare><value>100.00</value></transactionPricePerShare>
          <sharesOwnedFollowingTransaction><value>10000</value></sharesOwnedFollowingTransaction>
        </nonDerivativeTransaction>
      </nonDerivativeTable>
    </ownershipDocument>"""

    rows = parse_form4_xml(xml, 'TEST', '2026-01-16')
    assert len(rows) == 1
    assert rows[0]['footnotes'] is None, f"Expected None, got {rows[0]['footnotes']}"
    print(f"  PASS: no footnotes → footnotes=None")


# ── enrich_tenb51 integration test ───────────────────────────────────────────

def test_enrich_tenb51_uses_is_10b51_raw():
    """End-to-end: parser writes is_10b51_raw=1 → enricher returns is_10b51_plan=True."""
    import pandas as pd
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src.enrichment.enrich_tenb51 import enrich_tenb51

    df = pd.DataFrame([{
        'ticker': 'TEST',
        'insider_name': 'TEST PERSON',
        'transaction_type': 'SELL',
        'is_10b51_raw': 1,
        'footnotes': None,
    }])

    result = enrich_tenb51(df)
    plan = result['is_10b51_plan'].iloc[0]
    assert plan == True, f"Expected True, got {plan} (type={type(plan)})"
    print(f"  PASS: is_10b51_raw=1 → is_10b51_plan=True (enrich_tenb51 integration)")


def test_enrich_tenb51_uses_footnotes_when_raw_absent():
    """Enricher uses footnote regex when is_10b51_raw is None."""
    import pandas as pd
    from src.enrichment.enrich_tenb51 import enrich_tenb51

    df = pd.DataFrame([{
        'ticker': 'TEST',
        'insider_name': 'TEST PERSON',
        'transaction_type': 'SELL',
        'is_10b51_raw': None,
        'footnotes': 'Sale made pursuant to a pre-arranged plan (Rule 10b5-1).',
    }])

    result = enrich_tenb51(df)
    plan = result['is_10b51_plan'].iloc[0]
    assert plan == True, f"Expected True from footnote regex, got {plan} (type={type(plan)})"
    print(f"  PASS: footnote regex detected 10b5-1 plan → is_10b51_plan=True")


if __name__ == '__main__':
    print("=" * 60)
    print("FIX 4: 10b5-1 + FOOTNOTE EXTRACTION TESTS")
    print("=" * 60)
    tests = [
        test_10b51_raw_extracted_when_present,
        test_10b51_raw_none_when_absent,
        test_10b51_raw_zero_when_not_plan,
        test_footnotes_extracted_and_concatenated,
        test_footnotes_none_when_absent,
        test_enrich_tenb51_uses_is_10b51_raw,
        test_enrich_tenb51_uses_footnotes_when_raw_absent,
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
