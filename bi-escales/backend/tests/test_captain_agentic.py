from app.escales.captain_agentic import parse_agentic_proposal


def test_parse_create_invoice_proposal():
    proposal = parse_agentic_proposal(
        "Créer une facture 25,00 EUR pour donor@example.com",
        "fr",
    )
    assert proposal is not None
    assert proposal["kind"] == "create_invoice"
    assert proposal["requires_confirm"] is True
    assert proposal["preview"]["recipient_email"] == "donor@example.com"
    assert proposal["preview"]["amount_eur"] == "25.00"


def test_parse_create_order_proposal():
    proposal = parse_agentic_proposal("Create order 12 EUR for miles", "en")
    assert proposal is not None
    assert proposal["kind"] == "create_pledge_order"
