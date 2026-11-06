"""HTTP policies tested exclusively with mocked sandbox responses."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import httpx
import pytest

from app.escales.config import EscalesConfig
from app.escales import paypal_client, toolkit_tools
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


def test_captain_budget_counts_oauth_and_retry_attempts():
    seen = []
    def handle(request):
        seen.append(request)
        if request.url.path == '/v1/oauth2/token':
            return httpx.Response(200, json={'access_token': 'T', 'expires_in': 300})
        return httpx.Response(429, json={'debug_id': 'LIMIT'})
    client = PayPalClient(EscalesConfig('budget', 'secret'), httpx.MockTransport(handle))
    reader = ReadOnlyTools(client)
    with pytest.raises(PayPalCallLimitExceeded):
        reader.get('orders.get', 'O')
    with pytest.raises(PayPalCallLimitExceeded):
        reader.get('orders.get', 'O')
    assert len(seen) == 3


def test_failed_reads_use_budget_and_new_turn_has_fresh_budget():
    client = Mock()
    client.get_order.side_effect = PayPalError(503, {})
    reader = ReadOnlyTools(client)
    for _ in range(3):
        with pytest.raises(PayPalError):
            reader.get('orders.get', 'O')
    with pytest.raises(PayPalCallLimitExceeded):
        reader.get('orders.get', 'O')
    assert client.get_order.call_count == 3
    with pytest.raises(PayPalError):
        ReadOnlyTools(client).get('orders.get', 'O')
    assert client.get_order.call_count == 4


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


def test_captain_explains_a_summary_cut_short_by_the_call_cap():
    import asyncio
    from app.escales.captain import chat
    client = Mock()
    client.list_disputes.return_value = {'items': []}
    reader = ReadOnlyTools(client)
    for _ in range(3):
        reader.get('disputes.list')
    result = asyncio.run(chat('List PayPal disputes', treasurer=True, lang='en', reader=reader))
    assert 'summary may be partial' in result['reply']
    assert client.list_disputes.call_count == 3


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
