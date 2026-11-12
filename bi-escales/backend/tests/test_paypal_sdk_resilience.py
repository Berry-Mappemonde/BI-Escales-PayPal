"""SDK retries, accounting and request identity at the generated HTTP boundary."""
import pytest
import httpx
from tests import test_paypal_sdk_money_path as wire
from tests.test_paypal_sdk_money_path import pins  # noqa: F401
from app.escales import paypal_sdk_gateway as gateway
from app.escales.config import EscalesConfig
from app.escales.paypal_client import PayPalClient, PayPalError
from app.escales.paypal_limits import PayPalCallBudget, PayPalCallLimitExceeded


@pytest.fixture
def setup(pins, monkeypatch):
    monkeypatch.setenv('ESCALES_PAYPAL_SDK_ENABLED','1')
    records=[];wire._install(records)
    sleeps=[];monkeypatch.setattr(gateway.time,'sleep',sleeps.append)
    client=PayPalClient(EscalesConfig('test-client-id','test-secret'),transport=httpx.MockTransport(lambda r:pytest.fail('no httpx replay')))
    yield client,records,sleeps
    gateway.reset_client()


@pytest.mark.parametrize('write',[False,True])
@pytest.mark.parametrize('status',[429,503])
def test_retry_budget_and_stable_request_id(setup,monkeypatch,write,status):
    client,records,sleeps=setup
    original=wire._dispatch
    count=0
    def dispatch(method,path):
        nonlocal count
        if path=='/v1/oauth2/token': return original(method,path)
        count+=1
        return (status,{'name':'TEMPORARY'}) if count<3 else (200,{'id':'ORDER-OK','status':'CREATED'})
    monkeypatch.setattr(wire,'_dispatch',dispatch)
    client.captain_budget=PayPalCallBudget(remaining=3)
    result=client.create_capture_order('1.00','Donation','retry',idempotency_key='stable-retry') if write else client.get_order('ORDER-OK')
    assert result['id']=='ORDER-OK' and client.captain_budget.remaining==0
    resource=[r for r in records if r['path']!='/v1/oauth2/token']
    assert len(resource)==3 and len(sleeps)==2
    assert 0.25<=sleeps[0]<=0.5 and 0.5<=sleeps[1]<=0.75
    if write:
        assert {r['request_id'] for r in resource}=={'stable-retry'}
        assert resource[0]['body']==resource[1]['body']==resource[2]['body']


def test_budget_exhaustion_blocks_retry_and_context_resets(setup,monkeypatch):
    client,records,_=setup
    original=wire._dispatch
    monkeypatch.setattr(wire,'_dispatch',lambda method,path: original(method,path) if path=='/v1/oauth2/token' else (503,{'name':'TEMPORARY'}))
    client.captain_budget=PayPalCallBudget(remaining=1)
    with pytest.raises(PayPalCallLimitExceeded):client.create_capture_order('1.00','Donation','budget')
    assert len([r for r in records if r['path']!='/v1/oauth2/token'])==1
    monkeypatch.setattr(wire,'_dispatch',original)
    assert gateway.get_order('ORDER-AUTH')['id']=='ORDER-AUTH'


@pytest.mark.parametrize('retry_after,attempts',[('2',3),('11',1)])
def test_bounded_retry_after(setup,monkeypatch,retry_after,attempts):
    _,records,sleeps=setup
    original=wire._dispatch
    monkeypatch.setattr(wire,'_dispatch',lambda method,path:original(method,path) if path=='/v1/oauth2/token' else (429,{'name':'RATE_LIMIT'}))
    original_send=wire._Router.send
    def send(self,request,**kwargs):
        response=original_send(self,request,**kwargs);response.headers['Retry-After']=retry_after
        return response
    monkeypatch.setattr(wire._Router,'send',send)
    with pytest.raises(PayPalError) as exc:gateway.get_order('LIMIT')
    assert exc.value.status==429
    assert len([r for r in records if r['path']!='/v1/oauth2/token'])==attempts
    assert all(2<=pause<=2.25 for pause in sleeps)


def test_unsupported_model_field_is_mapped(setup):
    with pytest.raises(PayPalError) as exc:gateway.create_order({'intent':'CAPTURE','unsupported':True},idempotency_key='unsupported')
    assert exc.value.status==502
