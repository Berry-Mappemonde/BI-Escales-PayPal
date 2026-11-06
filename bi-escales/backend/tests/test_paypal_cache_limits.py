"""HTTP policies tested exclusively with mocked sandbox responses."""
from concurrent.futures import ThreadPoolExecutor
import asyncio
from unittest.mock import Mock

import httpx
import pytest

from app.escales.config import EscalesConfig
from app.escales import captain, ledger, paypal_client, toolkit_tools
from app.escales.paypal_client import PayPalClient, PayPalError
from app.escales.paypal_limits import PayPalCallLimitExceeded
from app.escales.toolkit_tools import ReadOnlyTools


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(paypal_client.time, 'sleep', Mock())
    monkeypatch.setattr(paypal_client.random, 'uniform', lambda a, b: 0.1)
    monkeypatch.setenv('ESCALES_TOOLKIT_ENABLED', '0')


def test_token_shared_across_clients_refreshed_before_expiry_and_isolated_by_credentials(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(paypal_client.time, 'monotonic', lambda: now[0])
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={'access_token': f'T-{len(seen)}', 'expires_in': 100})
    transport = httpx.MockTransport(handle)
    one = PayPalClient(EscalesConfig('id', 'secret'), transport)
    two = PayPalClient(EscalesConfig('id', 'secret'), transport)
    assert one._access_token() == two._access_token() == 'T-1'
    now[0] = 189
    assert two._access_token() == 'T-1'
    now[0] = 191
    assert one._access_token() == two._access_token() == 'T-2'
    other = PayPalClient(EscalesConfig('id', 'rotated-secret'), transport)
    assert other._access_token() == 'T-3'
    assert len(seen) == 3


def test_concurrent_token_refresh_is_single_flight():
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={'access_token': 'shared', 'expires_in': 300})
    transport = httpx.MockTransport(handle)
    clients = [PayPalClient(EscalesConfig('parallel', 'secret'), transport) for _ in range(4)]
    with ThreadPoolExecutor(max_workers=4) as executor:
        assert list(executor.map(lambda client: client._access_token(), clients)) == ['shared'] * 4
    assert len(seen) == 1


@pytest.mark.parametrize('status', [429, 500, 503])
def test_transient_resource_failures_retry_three_tries_with_jitter_and_stable_request_id(status):
    requests = []
    def handle(request):
        if request.url.path == '/v1/oauth2/token':
            return httpx.Response(200, json={'access_token': 'T', 'expires_in': 300})
        requests.append(request)
        return httpx.Response(status if len(requests) < 3 else 200, json={'id': 'CAP-1'})
    client = PayPalClient(EscalesConfig('retry', 'secret'), httpx.MockTransport(handle))
    assert client.capture_authorization('AUTH-1', idempotency_key='same-key')['id'] == 'CAP-1'
    assert len(requests) == 3
    assert {r.headers['PayPal-Request-Id'] for r in requests} == {'same-key'}
    assert len({r.content for r in requests}) == 1
    assert [c.args[0] for c in paypal_client.time.sleep.call_args_list] == [0.35, 0.6]


def test_oauth_retries_and_final_paypal_error_is_preserved():
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(503, json={'debug_id': 'LAST-DEBUG'})
    client = PayPalClient(EscalesConfig('failed-token', 'secret'), httpx.MockTransport(handle))
    with pytest.raises(PayPalError) as error:
        client.get_order('O')
    assert error.value.status == 503
    assert 'LAST-DEBUG' in error.value.body
    assert len(seen) == 3


@pytest.mark.parametrize('status', [400, 401, 403, 404, 422])
def test_non_transient_status_is_not_retried(status):
    seen = []
    def handle(request):
        if request.url.path == '/v1/oauth2/token':
            return httpx.Response(200, json={'access_token': 'T', 'expires_in': 300})
        seen.append(request)
        return httpx.Response(status, json={'debug_id': 'NO-RETRY'})
    client = PayPalClient(EscalesConfig('status', 'secret'), httpx.MockTransport(handle))
    with pytest.raises(PayPalError):
        client.get_order('O')
    assert len(seen) == 1
    paypal_client.time.sleep.assert_not_called()


def test_unkeyed_write_is_never_replayed():
    seen = []
    def handle(request):
        if request.url.path == '/v1/oauth2/token':
            return httpx.Response(200, json={'access_token': 'T', 'expires_in': 300})
        seen.append(request)
        return httpx.Response(500, json={})
    client = PayPalClient(EscalesConfig('unsafe-write', 'secret'), httpx.MockTransport(handle))
    with pytest.raises(PayPalError):
        client._req('POST', '/v2/invoicing/invoices/INV/send', paypal_idempotent=False)
    assert len(seen) == 1


def test_chat_budget_excludes_oauth_and_counts_resource_retry_attempts():
    seen = []
    def handle(request):
        seen.append(request)
        if request.url.path == '/v1/oauth2/token':
            return httpx.Response(200, json={'access_token': 'T', 'expires_in': 300})
        return httpx.Response(429, json={'debug_id': 'LIMIT'})
    client = PayPalClient(EscalesConfig('budget', 'secret'), httpx.MockTransport(handle))
    reader = ReadOnlyTools(client)
    with reader.chat_turn():
        with pytest.raises(PayPalError) as error:
            reader.get('orders.get', 'O')
        assert error.value.status == 429
        with pytest.raises(PayPalCallLimitExceeded):
            reader.get('orders.get', 'O')
    assert sum(r.url.path == '/v1/oauth2/token' for r in seen) == 1
    assert sum(r.url.path.endswith('/O') for r in seen) == 3
    assert len(seen) == 4
    assert reader.call_log[0]['debug_id'] == 'LIMIT'
    assert reader.call_log[1]['status'] == 'error'
    assert client.captain_budget is None


def test_cold_token_leaves_all_three_chat_resource_calls_available():
    seen = []
    def handle(request):
        seen.append(request)
        if request.url.path == '/v1/oauth2/token':
            return httpx.Response(200, json={'access_token': 'T', 'expires_in': 300})
        return httpx.Response(200, json={'id': request.url.path.rsplit('/', 1)[-1]})
    client = PayPalClient(EscalesConfig('cold-budget', 'secret'), httpx.MockTransport(handle))
    reader = ReadOnlyTools(client)
    with reader.chat_turn():
        for id in ['one', 'two', 'three']:
            assert reader.get('orders.get', id)['id'] == id
        with pytest.raises(PayPalCallLimitExceeded):
            reader.get('orders.get', 'four')
    assert len(seen) == 4
    # Ending chat restores unbudgeted reads, including on a reused client.
    assert reader.get('orders.get', 'review')['id'] == 'review'
    assert len(seen) == 5


def test_failed_reads_use_chat_budget_and_each_new_turn_has_fresh_budget():
    client = Mock()
    client.get_order.side_effect = PayPalError(503, {})
    reader = ReadOnlyTools(client)
    for _ in range(2):
        with reader.chat_turn():
            for _ in range(3):
                with pytest.raises(PayPalError):
                    reader.get('orders.get', 'O')
            with pytest.raises(PayPalCallLimitExceeded):
                reader.get('orders.get', 'O')
    assert client.get_order.call_count == 6


@pytest.mark.parametrize('use_toolkit', [False, True])
def test_review_reads_all_six_resources_for_three_pledges(monkeypatch, use_toolkit):
    from app.core import llm
    monkeypatch.setattr(llm, 'has_llm', lambda *a, **kw: False)
    monkeypatch.setattr(ledger, '_ledger', ledger.MemoryLedger())
    monkeypatch.setenv('ESCALES_CLOCK_NOW', '2026-11-12T12:00:00Z')
    toolkit_reads = []
    if use_toolkit:
        def execute(adapter, params):
            toolkit_reads.append(params['order_id'])
            return adapter.get('/v2/checkout/orders/' + params['order_id'])
        monkeypatch.setattr(toolkit_tools, '_toolkit_tools', lambda: [{
            'actions': toolkit_tools.TOOLKIT_ORDER_ACTIONS, 'method': 'get_order_details', 'execute': execute,
        }])
    seen = []
    def handle(request):
        seen.append(request)
        if request.url.path == '/v1/oauth2/token':
            return httpx.Response(200, json={'access_token': 'T', 'expires_in': 300})
        assert request.method == 'GET'
        return httpx.Response(200, json={'id': request.url.path.rsplit('/', 1)[-1], 'status': 'CREATED'})
    client = PayPalClient(EscalesConfig('three-pledges', 'secret'), httpx.MockTransport(handle))
    reader = ReadOnlyTools(client)
    async def run():
        for n in range(3):
            await ledger.get_ledger().insert_pledge_once({
                '_id': f'pledge-{n}', 'milestone_id': 'dep-la-rochelle', 'status': 'authorized',
                'amount_eur': '5.00', 'order_id': f'ORDER-{n}', 'authorization_id': f'AUTH-{n}',
            })
        return await captain.review('dep-la-rochelle', reader=reader, lang='en')
    result = asyncio.run(run())
    expected = {f'/v2/checkout/orders/ORDER-{n}' for n in range(3)} | {
        f'/v2/payments/authorizations/AUTH-{n}' for n in range(3)
    }
    resource_paths = [r.url.path for r in seen if r.url.path != '/v1/oauth2/token']
    assert len(resource_paths) == 6
    assert set(resource_paths) == expected
    assert len(seen) == 7  # One OAuth fetch, then all six resource reads.
    assert len(result['paypal_tools']['calls']) == 6
    assert all(call['status'] == 'ok' and call['read_only'] and call['latency_ms'] >= 0
               for call in result['paypal_tools']['calls'])
    assert toolkit_reads == ([f'ORDER-{n}' for n in range(3)] if use_toolkit else [])


def test_toolkit_adapter_reuses_the_same_oauth_cache(monkeypatch):
    seen = []
    def handle(request):
        seen.append(request)
        if request.url.path == '/v1/oauth2/token':
            return httpx.Response(200, json={'access_token': 'T', 'expires_in': 300})
        return httpx.Response(200, json={'id': request.url.path.rsplit('/', 1)[-1]})
    transport = httpx.MockTransport(handle)
    def execute(adapter, params):
        return adapter.get('/v2/checkout/orders/' + params['order_id'])
    monkeypatch.setattr(toolkit_tools, '_toolkit_tools', lambda: [{
        'actions': toolkit_tools.TOOLKIT_ORDER_ACTIONS, 'method': 'get_order_details', 'execute': execute,
    }])
    for id in ['one', 'two']:
        reader = ReadOnlyTools(PayPalClient(EscalesConfig('toolkit-cache', 'secret'), transport))
        assert reader.uses_toolkit
        assert reader.get('orders.get', id)['id'] == id
    assert sum(r.url.path == '/v1/oauth2/token' for r in seen) == 1
    assert len(seen) == 3


def test_long_retry_after_stops_instead_of_retrying_too_early():
    attempts = []
    def handle(request):
        if request.url.path == '/v1/oauth2/token':
            return httpx.Response(200, json={'access_token': 'T', 'expires_in': 300})
        attempts.append(request)
        return httpx.Response(429 if len(attempts) == 1 else 200, headers={'Retry-After': '3600'}, json={})
    client = PayPalClient(EscalesConfig('retry-after', 'secret'), httpx.MockTransport(handle))
    with pytest.raises(PayPalError) as error:
        client.get_order('O')
    assert error.value.status == 429
    assert len(attempts) == 1
    paypal_client.time.sleep.assert_not_called()


def test_unauthorized_token_is_not_reused_on_the_next_request():
    seen = []
    resource_calls = []
    def handle(request):
        if request.url.path == '/v1/oauth2/token':
            seen.append(request)
            return httpx.Response(200, json={'access_token': f'T-{len(seen)}', 'expires_in': 300})
        resource_calls.append(request)
        return httpx.Response(401 if len(resource_calls) == 1 else 200, json={})
    client = PayPalClient(EscalesConfig('revoked', 'secret'), httpx.MockTransport(handle))
    with pytest.raises(PayPalError):
        client.get_order('O')
    client.get_order('O')
    assert len(seen) == 2
    assert resource_calls[1].headers['Authorization'] == 'Bearer T-2'


@pytest.mark.parametrize('payload', [{}, {'access_token': 'T', 'expires_in': -1}, [], {'access_token': 'T', 'expires_in': 'invalid'}])
def test_invalid_oauth_response_is_not_cached(payload):
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    client = PayPalClient(EscalesConfig('invalid', 'secret'), transport)
    with pytest.raises(PayPalError, match='502'):
        client._access_token()
    assert client._cached_token.token is None


def test_chat_scopes_its_budget_and_explains_a_summary_cut_short_by_the_cap(monkeypatch):
    client = Mock()
    client.list_disputes.return_value = {'items': []}
    reader = ReadOnlyTools(client)
    original = captain._paypal_readonly_reply
    def read_more(message, lang, reader):
        for _ in range(3):
            reader.get('disputes.list')
        return original(message, lang, reader)  # A fourth attempt must stop before HTTP.
    monkeypatch.setattr(captain, '_paypal_readonly_reply', read_more)
    for _ in range(2):
        result = asyncio.run(captain.chat('List PayPal disputes', treasurer=True, lang='en', reader=reader))
        assert 'summary may be partial' in result['reply']
    assert client.list_disputes.call_count == 6
    # A later review/read with the same reader is not limited by the previous chat.
    reader.get('disputes.list')
    assert client.list_disputes.call_count == 7


def test_chat_restores_the_client_budget_after_an_exception(monkeypatch):
    client = PayPalClient(EscalesConfig('exception', 'secret'), httpx.MockTransport(lambda _: httpx.Response(200)))
    reader = ReadOnlyTools(client)
    async def fail(*args, **kwargs):
        assert client.captain_budget is not None
        raise ValueError('chat failed')
    monkeypatch.setattr(captain, '_chat', fail)
    with pytest.raises(ValueError, match='chat failed'):
        asyncio.run(captain.chat('hello', reader=reader))
    assert client.captain_budget is None


def test_numeric_retry_after_is_respected():
    attempts = []
    def handle(request):
        if request.url.path == '/v1/oauth2/token':
            return httpx.Response(200, json={'access_token': 'T', 'expires_in': 300})
        attempts.append(request)
        return httpx.Response(429 if len(attempts) == 1 else 200, headers={'Retry-After': '2'}, json={})
    client = PayPalClient(EscalesConfig('short-retry-after', 'secret'), httpx.MockTransport(handle))
    client.get_order('O')
    assert len(attempts) == 2
    assert paypal_client.time.sleep.call_args.args[0] == 2.1
