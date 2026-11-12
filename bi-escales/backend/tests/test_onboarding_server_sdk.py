"""Onboarding Orders use an isolated Platform SDK at its HTTP boundary."""
import base64
import json
import threading
from urllib.parse import urlparse
import pytest
import requests
from requests.adapters import HTTPAdapter
import httpx
from app.escales.config import EscalesConfig
from app.escales.paypal_client import PayPalClient, PayPalError
from app.project_onboarding import paypal_orders as orders


@pytest.fixture
def sdk_transport(monkeypatch):
    import paypalserversdk.paypal_serversdk_client as module
    from app.escales import paypal_sdk_gateway as merchant
    monkeypatch.setenv('PAYPAL_ENV','sandbox')
    monkeypatch.setenv('ESCALES_PAYPAL_SDK_ENABLED','1')
    monkeypatch.setenv('PAYPAL_PLATFORM_CLIENT_ID','platform-test')
    monkeypatch.setenv('PAYPAL_PLATFORM_CLIENT_SECRET','platform-secret')
    monkeypatch.setenv('PAYPAL_CLIENT_ID','merchant-test')
    monkeypatch.setenv('PAYPAL_CLIENT_SECRET','merchant-secret')
    monkeypatch.setenv('PAYPAL_BN_CODE','TEST_BN')
    monkeypatch.setattr(merchant,'client',lambda:pytest.fail('merchant singleton forbidden'))
    rows=[];created=[];state={'error':False}
    class Adapter(HTTPAdapter):
        def send(self,request,**kwargs):
            path=urlparse(request.url).path
            rows.append(request)
            if path=='/v1/oauth2/token':
                assert request.headers['Authorization']=='Basic '+base64.b64encode(b'platform-test:platform-secret').decode()
                payload={'access_token':'platform-token','token_type':'Bearer','expires_in':3600};status=200
            else:
                assert request.headers['Authorization']=='Bearer platform-token'
                status=422 if state['error'] else 200
                needle=state.get('transient_path')
                if state.get('transient',0) and (not needle or needle in path):
                    state['transient']-=1;status=503
                state.setdefault('threads',[]).append(threading.get_ident())
                payload={'name':'UNPROCESSABLE_ENTITY','details':[{'issue':'INSTRUMENT_DECLINED'}]} if state['error'] else {'id':'ORDER-PLATFORM','status':'COMPLETED'}
                if status < 400 and isinstance(state.get('by_method'), dict):
                    payload = state['by_method'].get(request.method, payload)
            response=requests.Response();response.status_code=status;response._content=json.dumps(payload).encode();response.headers['Content-Type']='application/json';response.request=request;response.url=request.url
            return response
    original=module.PaypalServersdkClient
    def build(**kwargs):
        session=requests.Session();session.mount('https://',Adapter())
        kwargs['http_client_instance']=session
        sdk=original(**kwargs);created.append(sdk);return sdk
    monkeypatch.setattr(module,'PaypalServersdkClient',build)
    client=PayPalClient(EscalesConfig('merchant-test','merchant-secret'),transport=httpx.MockTransport(lambda r:pytest.fail('no HTTP fallback')))
    return client,rows,created,state


def test_platform_credentials_bn_and_stable_capture(sdk_transport):
    client,rows,created,_=sdk_transport
    result=orders.create_unlinked_payee_capture_order(client,amount_eur='7.35',description='Gift',project_id='project-test',payee_email='project@example.test',donation_id='donation-test',return_url='https://example.test/return',cancel_url='https://example.test/cancel',checkout_locale='fr-FR')
    assert result['id']=='ORDER-PLATFORM'
    assert orders.read_order(client,'ORDER-PLATFORM')['id']=='ORDER-PLATFORM'
    orders.capture_order_once(client,'ORDER-PLATFORM');orders.capture_order_once(client,'ORDER-PLATFORM')
    assert len(created)==1
    resource=[r for r in rows if urlparse(r.url).path!='/v1/oauth2/token']
    assert resource[0].headers['PayPal-Partner-Attribution-Id']=='TEST_BN'
    body=json.loads(resource[0].body)
    assert body['intent']=='CAPTURE' and body['purchase_units'][0]['payee']=={'email_address':'project@example.test'}
    assert body['purchase_units'][0]['amount']=={'currency_code':'EUR','value':'7.35'}
    assert body['payment_source']['paypal']['experience_context']['locale']=='fr-FR'
    assert resource[2].headers['PayPal-Request-Id']==resource[3].headers['PayPal-Request-Id']
    assert resource[2].headers['Prefer']=='return=representation'


def test_sdk_error_is_mapped_without_merchant_or_http_replay(sdk_transport):
    client,rows,_,state=sdk_transport;state['error']=True
    with pytest.raises(PayPalError) as exc:orders.capture_order_once(client,'ORDER-PLATFORM')
    assert exc.value.status==422
    assert len(rows)==2 # OAuth + one resource attempt


def test_platform_client_rejects_non_sandbox(sdk_transport,monkeypatch):
    client,*_=sdk_transport
    monkeypatch.setenv('PAYPAL_ENV','live')
    with pytest.raises(RuntimeError,match='sandbox'):orders.read_order(client,'ORDER-PLATFORM')


def test_platform_uses_shared_gateway_transient_retry(sdk_transport,monkeypatch):
    from app.escales import paypal_sdk_gateway as gateway
    client,rows,_,state=sdk_transport
    state['transient']=1
    pauses=[];monkeypatch.setattr(gateway.time,'sleep',pauses.append)
    assert orders.capture_order_once(client,'ORDER-PLATFORM')['id']=='ORDER-PLATFORM'
    resources=[r for r in rows if urlparse(r.url).path!='/v1/oauth2/token']
    assert len(resources)==2 and len(pauses)==1
    assert resources[0].headers['PayPal-Request-Id']==resources[1].headers['PayPal-Request-Id']


def test_onboarding_create_and_capture_leave_the_event_loop(sdk_transport, monkeypatch):
    """Project donation order create and capture must not run the SDK on the event loop."""
    import asyncio

    from app.escales import paypal_sdk_gateway as gateway
    from app.project_onboarding import service
    from app.project_onboarding.store import reset_onboarding_store, save_project

    client, _, _, state = sdk_transport
    monkeypatch.setenv("ESCALES_ONBOARD_AFTER_PAYMENT_ENABLED", "1")
    monkeypatch.setenv("ESCALES_STORE", "memory")
    reset_onboarding_store()

    async def link(*_args, **_kwargs):
        return {"action_url": "https://example.test/onboard"}

    monkeypatch.setattr(service, "ensure_onboarding_link", link)
    main = threading.get_ident()
    waiting = threading.Event()
    heartbeat = threading.Event()

    def backoff(_delay):
        assert threading.get_ident() != main, "SDK retry blocked the event loop"
        waiting.set()
        assert heartbeat.wait(2), "event loop could not run while PayPal waited"

    monkeypatch.setattr(gateway.time, "sleep", backoff)

    async def drive(task):
        while not waiting.is_set():
            await asyncio.sleep(0.001)
        heartbeat.set()
        return await task

    async def run():
        await save_project({
            "_id": "project-off-loop",
            "title_fr": "Projet",
            "onboarding_status": "pending",
        })
        state["transient"] = 1
        state["threads"] = []
        created = await drive(asyncio.create_task(service.create_donation_order(
            "project-off-loop",
            amount_eur="5.00",
            client=client,
            return_url="https://example.test/return",
            cancel_url="https://example.test/cancel",
        )))
        assert created["order_id"] == "ORDER-PLATFORM"
        assert state["threads"] and main not in state["threads"]

        waiting.clear()
        heartbeat.clear()
        state["transient"] = 1
        state["transient_path"] = "/capture"
        state["threads"] = []
        state["by_method"] = {
            "GET": {
                "id": "ORDER-PLATFORM",
                "status": "APPROVED",
                "purchase_units": [{
                    "reference_id": created["_id"],
                    "custom_id": "project-off-loop",
                }],
            },
            "POST": {
                "id": "ORDER-PLATFORM",
                "status": "COMPLETED",
                "purchase_units": [{
                    "payments": {"captures": [{"id": "CAP-OFF", "status": "COMPLETED"}]},
                }],
            },
        }
        captured = await drive(asyncio.create_task(service.finalize_donation_capture(
            created["_id"], client=client,
        )))
        assert captured["capture_id"] == "CAP-OFF"
        assert state["threads"] and main not in state["threads"]
        reset_onboarding_store()

    asyncio.run(asyncio.wait_for(run(), timeout=4))
