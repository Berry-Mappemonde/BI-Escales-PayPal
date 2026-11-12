"""Free stop gifts reuse arrival settlement and keep held money out of Net."""
import asyncio
import datetime as dt
import json
import pytest
from app.escales.pledges import create_pledge, authorize_pledge, capture_pledge, refund_pledge
from app.escales.ledger import get_ledger, reset_ledger, fund_for_milestone
from app.escales.departure_clock import run_departure_clock, refuse_early_capture
from app.escales.payment_mode import preview_payment_mode
from tests.test_escales_pledges import Spy
from tests.review_helpers import approve_capture_review

STOP='dep-dzaoudzi-mayotte'
from app.escales.naviguide_bridge import _stop_shell_meta
ARRIVAL=dt.datetime.fromisoformat(_stop_shell_meta(STOP)['arrival_iso'].replace('Z','+00:00'))
NOW=ARRIVAL-dt.timedelta(hours=48)


@pytest.fixture(autouse=True)
def memory(monkeypatch):
    monkeypatch.setenv('ESCALES_STORE','memory');monkeypatch.setenv('ESCALES_CLOCK_NOW',NOW.isoformat());monkeypatch.setenv('ESCALES_VAULT_ENABLED','1')
    reset_ledger();yield;reset_ledger()


async def schedule(hours=48,cancelled=False):
    await get_ledger().ensure_milestone(STOP,meta={'capture_on':'arrival','arrival_iso':(NOW+dt.timedelta(hours=hours)).isoformat(),'cancelled':cancelled})


async def gift(client,**kwargs):
    return await create_pledge(amount_eur=kwargs.pop('amount_eur','17.35'),description='Private donor description',milestone_id=kwargs.pop('milestone_id',STOP),kind='stop_gift',client=client,**kwargs)


def test_free_amount_and_held_vs_captured_refunded_totals(monkeypatch):
    async def run():
        await schedule();spy=Spy();created=await gift(spy)
        assert created['kind']=='stop_gift' and created['amount_eur']=='17.35' and created['payment_mode']=='AUTHORIZE'
        assert not any(c[0]=='create_capture' for c in spy.calls)
        held=await authorize_pledge(created['_id'],spy)
        totals=await fund_for_milestone(STOP)
        assert totals['captured_eur']=='0.00' and totals['refunded_eur']=='0.00' and totals['authorized_eur']=='17.35'
        with pytest.raises(ValueError,match='stop arrival'):await refuse_early_capture(held,now=NOW)
        arrival=NOW+dt.timedelta(hours=48);monkeypatch.setenv('ESCALES_CLOCK_NOW',arrival.isoformat())
        first=await run_departure_clock(spy,now=arrival)
        assert first['actions'][0]['action']=='await_review_approval'
        await approve_capture_review(STOP)
        settled=await run_departure_clock(spy,now=arrival)
        assert settled['actions'][0]['action']=='capture'
        totals=await fund_for_milestone(STOP)
        assert totals['captured_eur']=='17.35' and totals['authorized_eur']=='0.00'
        entries=await get_ledger().list_finance()
        assert any(e.get('pledge_kind')=='stop_gift' and e['kind']=='pledge_captured' for e in entries)
        await refund_pledge(created['_id'],spy,amount_eur='2.35',request_key='gift-partial')
        totals=await fund_for_milestone(STOP)
        assert totals['captured_eur']=='17.35' and totals['refunded_eur']=='2.35' and totals['authorized_eur']=='0.00'
    asyncio.run(run())


def test_cancelled_stop_voids_gift_and_excludes_all_totals():
    async def run():
        await schedule();spy=Spy();created=await gift(spy);await authorize_pledge(created['_id'],spy)
        await get_ledger().ensure_milestone(STOP,meta={'capture_on':'arrival','arrival_iso':(NOW+dt.timedelta(hours=48)).isoformat(),'cancelled':True})
        result=await run_departure_clock(spy,now=NOW)
        assert result['actions'][0]['action']=='void'
        assert (await get_ledger().get_pledge(created['_id']))['status']=='voided'
        totals=await fund_for_milestone(STOP)
        assert all(totals[k]=='0.00' for k in ('captured_eur','refunded_eur','authorized_eur'))
    asyncio.run(run())


@pytest.mark.parametrize('amount',['0.01','7.35','123.47'])
def test_gift_has_no_unit_price(amount):
    async def run():
        await schedule();assert (await gift(Spy(),amount_eur=amount))['amount_eur']==amount
    asyncio.run(run())


@pytest.mark.parametrize('extra',[{'quantity':2},{'target_id':'dep-dakar'},{'milestone_id':'leg-not-a-stop'},{'milestone_id':''},{'amount_eur':'0.00'}])
def test_invalid_gift_rejected_before_provider(extra):
    async def run():
        await schedule();spy=Spy()
        with pytest.raises(ValueError):await gift(spy,**extra)
        assert spy.calls==[]
    asyncio.run(run())


@pytest.mark.parametrize('hours,mode',[(48,'AUTHORIZE'),(695,'AUTHORIZE'),(695+1/3600,'VAULT'),(720,'VAULT')])
def test_preview_and_creation_reuse_mode_policy(hours,mode,monkeypatch):
    monkeypatch.setenv('ESCALES_CLOCK_NOW',(ARRIVAL-dt.timedelta(hours=hours)).isoformat())
    class VaultSpy(Spy):
        def create_setup_token(self,*args,**kwargs):return {'id':'SETUP','links':[{'rel':'approve','href':'https://www.sandbox.paypal.com/setup'}]}
    async def run():
        await schedule(hours);assert await preview_payment_mode(STOP,'stop_gift')==mode
        assert (await gift(VaultSpy()))['payment_mode']==mode
    asyncio.run(run())


def test_captain_model_prompts_do_not_receive_gift_rows(monkeypatch):
    from app.escales import captain
    prompts=[]
    async def narrative(prompt,*args,**kwargs):prompts.append(json.loads(prompt));return None,{},'en'
    async def advisory(payload,age):prompts.append(payload);return None
    monkeypatch.setattr(captain,'_narrative_for_language',narrative);monkeypatch.setattr(captain,'_advisory_proposal',advisory)
    async def run():
        await schedule();spy=Spy();created=await gift(spy);held=await authorize_pledge(created['_id'],spy)
        await captain.review(STOP,lang='en')
        encoded=json.dumps(prompts)
        for forbidden in (created['_id'],held['authorization_id'],'Private donor description','17.35'):
            assert forbidden not in encoded
    asyncio.run(run())
