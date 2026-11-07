import asyncio
from unittest.mock import AsyncMock
import pytest
from app.escales import pledges

@pytest.mark.parametrize('kind,unit', [('mile',1),('night',60),('meal',60),('care',40),('berth',30),('cabin_leg',80)])
def test_quantity_rejects_mismatched_amount_before_paypal(kind, unit):
    with pytest.raises(ValueError, match='unit price'):
        asyncio.run(pledges.create_pledge(quantity=3, amount_eur=f'{unit:.2f}', description='Units', milestone_id='dep-mayotte', kind=kind, client=object()))

@pytest.mark.parametrize('quantity', [0,1001,True,1.5])
def test_invalid_quantity(quantity):
    with pytest.raises(ValueError, match='quantity'):
        asyncio.run(pledges.create_pledge(quantity=quantity, amount_eur='3.00', kind='mile'))

def test_quantity_uses_server_computed_total(monkeypatch):
    create = AsyncMock(return_value={'_id':'Q', 'quantity':3})
    monkeypatch.setattr(pledges, '_create_pledge', create)
    asyncio.run(pledges.create_pledge(quantity=3, amount_eur='090.00', kind='berth'))
    assert create.call_args.kwargs['amount_eur'] == '90.00'

def test_post_rejects_mismatched_quantity(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers import escales
    monkeypatch.setenv('ESCALES_ENABLED', '1')
    monkeypatch.setattr(escales, '_paypal', lambda *_args: object())
    app = FastAPI(); app.include_router(escales.router)
    response = TestClient(app).post('/api/escales/pledges', json={
        'kind':'berth', 'quantity':3, 'amount_eur':'30.00',
        'description':'3 berths', 'milestone_id':'dep-mayotte'})
    assert response.status_code == 422
    assert 'unit price' in str(response.json())
