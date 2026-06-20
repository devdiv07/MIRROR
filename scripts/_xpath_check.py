"""Verify XPath for aff10b5One and footnotes in Form 4 XML."""
import xml.etree.ElementTree as ET

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
  <footnotes>
    <footnote id="F1">This sale was made pursuant to a Rule 10b5-1 plan.</footnote>
    <footnote id="F2">Represents tax withholding only.</footnote>
  </footnotes>
</ownershipDocument>"""

root = ET.fromstring(xml)

# aff10b5One is a root-level tag (not inside the transaction block)
aff_root = root.find('aff10b5One')
print('aff10b5One at root:', aff_root.text if aff_root is not None else 'NOT FOUND')

# Also check with .// for deeper search
aff_deep = root.find('.//aff10b5One')
print('aff10b5One via .//:', aff_deep.text if aff_deep is not None else 'NOT FOUND')

# Check inside tx block (should NOT be there per SEC schema)
for tx in root.findall('.//nonDerivativeTransaction'):
    aff_tx = tx.find('aff10b5One')
    print('aff10b5One inside tx block:', aff_tx.text if aff_tx is not None else 'NOT FOUND')

# Footnotes
footnotes = [f.text.strip() for f in root.findall('.//footnote') if f.text]
print('footnotes:', footnotes)
# use of this script for temporary audit and debugging purposes, not for production use
#we can delete this script after we confirm the xpath for aff10b5One and footnotes in Form 4 XML
