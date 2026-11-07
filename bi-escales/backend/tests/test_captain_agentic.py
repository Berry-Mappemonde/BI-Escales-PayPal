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


def test_invoice_amount_ignores_digits_in_email():
    proposal = parse_agentic_proposal("Create invoice user123@example.com for 50 EUR", "en")
    assert proposal is not None
    assert proposal["preview"]["recipient_email"] == "user123@example.com"
    assert proposal["preview"]["amount_eur"] == "50.00"


def test_invoice_amount_prefers_currency_marker_fr():
    proposal = parse_agentic_proposal("Créer une facture pour bob99@marina.fr de 12,50 €", "fr")
    assert proposal is not None
    assert proposal["preview"]["amount_eur"] == "12.50"


def test_order_amount_ignores_identifier_digits():
    proposal = parse_agentic_proposal("Create order for user42 of 18 euros", "en")
    assert proposal is not None
    assert proposal["preview"]["amount_eur"] == "18.00"
