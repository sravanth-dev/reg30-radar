"""`parse_stage` must not read the standard "(as amended)" legal boilerplate as an order
amendment. BDL's new ₹810.79 crore order was labelled "amendment" because every filing
cites "Regulation 30 of SEBI (LODR) Regulations, 2015, (as amended)" (WORKLOG, 24 Sep)."""

from reg30_radar.extractor.annexure import parse_stage

BDL = (
    "Subject: Receipt of orders- Reg.\n"
    "Pursuant to Regulation 30 of SEBI (LODR) Regulations, 2015, (as amended) we\n"
    "wish to inform that today BDL has signed a contract with Ministry of Defence "
    "for supply of missiles worth Rs. 810.79 Crore."
)


def test_legal_boilerplate_is_not_an_amendment():
    assert parse_stage(BDL) == "contract"


def test_a_real_amendment_of_an_order_is_still_found():
    text = BDL + "\nThis is an amendment to the purchase order received on 2 Sep 2026."
    assert parse_stage(text) == "amendment"


def test_termination_of_a_contract_is_an_amendment():
    assert parse_stage("The client has terminated the contract dated 1 Aug.") == "amendment"


def test_non_cancellable_order_is_not_an_amendment():
    # AASTHA, 25 Sep: "secured one, long-term, non-cancellable order".
    assert parse_stage("has secured one, long-term, non-cancellable order") == "unknown"
