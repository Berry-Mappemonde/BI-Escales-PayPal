import asyncio
import datetime as dt
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.escales.ledger import get_ledger, reset_ledger
from app.escales.pledges import create_pledge
from app.routers.escales import router

class PayPalSpy:
    def create_authorize_order(self, **kwargs):
        return {'id':'ORDER', 'links':[{'rel':'approve','href':'https://sandbox.paypal.com/order'}]}
    def create_setup_token(self, *args, **kwargs):
        return {'id':'SETUP', 'links':[{'rel':'approve','href':'https://sandbox.paypal.com/setup'}]}

@pytest.fixture(autouse=True)
def memory(monkeypatch):
    monkeypatch.setenv('ESCALES_ENABLED','1')
    monkeypatch.setenv('ESCALES_STORE','memory')
    monkeypatch.setenv('ESCALES_CLOCK_NOW','2026-11-19T08:00:00Z')
    monkeypatch.setenv('ESCALES_VAULT_ENABLED','1')
    reset_ledger()
    yield
    reset_ledger()

@pytest.mark.parametrize('days,mode',[(28,'AUTHORIZE'),(29,'AUTHORIZE'),(30,'VAULT'),(60,'VAULT')])
def test_mode_preview_matches_creation_without_writes(days, mode):
    ledger=get_ledger()
    anchor=dt.datetime(2026,11,19,8,tzinfo=dt.timezone.utc)+dt.timedelta(days=days)
    asyncio.run(ledger.ensure_milestone('dep-mode-preview',meta={'capture_on':'arrival','arrival_iso':anchor.isoformat()}))
    app=FastAPI();app.include_router(router)
    with patch.object(ledger,'ensure_milestone',side_effect=AssertionError('GET must not write milestones')), patch.object(ledger,'insert_pledge_once',side_effect=AssertionError('GET must not insert pledges')):
        response=TestClient(app).get('/api/escales/pledges/mode',params={'milestone_id':'dep-mode-preview','kind':'mile'})
    assert response.status_code==200
    assert response.json()=={'payment_mode':mode}
    assert asyncio.run(ledger.list_pledges())==[]
    created=asyncio.run(create_pledge(amount_eur='5.00',description='Preview match',milestone_id='dep-mode-preview',kind='mile',client=PayPalSpy()))
    assert created['payment_mode']==mode


def test_frozen_schedule_preview_does_not_create_milestone():
    ledger=get_ledger(); app=FastAPI();app.include_router(router)
    with patch.object(ledger,'ensure_milestone',side_effect=AssertionError('GET must not write')):
        response=TestClient(app).get('/api/escales/pledges/mode',params={'milestone_id':'dep-dzaoudzi-mayotte','kind':'berth'})
    assert response.status_code==200
    assert asyncio.run(ledger.get_milestone('dep-dzaoudzi-mayotte')) is None


def test_vault_off_long_horizon_matches_creation_error(monkeypatch):
    monkeypatch.setenv('ESCALES_VAULT_ENABLED','0')
    app=FastAPI();app.include_router(router)
    response=TestClient(app).get('/api/escales/pledges/mode',params={'milestone_id':'dep-dzaoudzi-mayotte','kind':'mile'})
    assert response.status_code==422
    with pytest.raises(ValueError,match='29 days'):
        asyncio.run(create_pledge(amount_eur='5.00',description='Disabled Vault',milestone_id='dep-dzaoudzi-mayotte',kind='mile',client=PayPalSpy()))


def test_unknown_milestone_rejected_without_writes():
    app=FastAPI();app.include_router(router)
    response=TestClient(app).get('/api/escales/pledges/mode',params={'milestone_id':'not-a-stop','kind':'mile'})
    assert response.status_code==422
    assert asyncio.run(get_ledger().list_pledges())==[]


@pytest.mark.parametrize('days', [28, 30])
def test_cabin_preview_uses_leg_departure(days, monkeypatch):
    from app.escales.naviguide_bridge import clock_legs
    leg = clock_legs()[0]
    anchor = dt.datetime.fromisoformat(leg['departure_iso'].replace('Z','+00:00'))
    monkeypatch.setenv('ESCALES_CLOCK_NOW',(anchor-dt.timedelta(days=days)).isoformat())
    app=FastAPI();app.include_router(router)
    response=TestClient(app).get('/api/escales/pledges/mode',params={'milestone_id':leg['id'],'kind':'cabin_leg'})
    assert response.status_code==200
    created=asyncio.run(create_pledge(amount_eur='80.00',description='Cabin',milestone_id=leg['id'],kind='cabin_leg',client=PayPalSpy()))
    assert response.json()['payment_mode']==created['payment_mode']
    assert created['payment_mode']==('AUTHORIZE' if days==28 else 'VAULT')
