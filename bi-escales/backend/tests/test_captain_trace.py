import asyncio
from unittest.mock import Mock

import pytest

from app.escales import ledger
from app.escales.captain import chat, review
from app.escales.paypal_client import PayPalError
from app.escales.toolkit_tools import ReadOnlyTools


@pytest.fixture
def reader(monkeypatch):
    monkeypatch.setenv('ESCALES_TOOLKIT_ENABLED', '0')
    monkeypatch.setattr(ledger, '_ledger', ledger.MemoryLedger())
    from app.core import llm
    monkeypatch.setattr(llm, 'has_llm', lambda *a, **kw: False)
    return ReadOnlyTools(Mock())


def test_deterministic_summary_reports_rules_and_each_attempt(reader):
    reader._calls['invoices.list'] = lambda _: {'items': []}
    result = asyncio.run(chat('List PayPal invoices', treasurer=True, lang='en', reader=reader))
    assert result['model_label'] == 'rules'
    assert result['latency_ms'] >= 0
    call = result['paypal_tools']['calls'][0]
    assert call['tool'] == 'invoices.list'
    assert call['resource_id'] == '1'
    assert call['read_only'] is True
    assert call['latency_ms'] >= 0
    assert call['status'] == 'ok'


def test_paypal_failure_trace_keeps_debug_id_without_raw_payload(reader):
    def fail(_):
        raise PayPalError(503, '{"debug_id":"DEBUG-safe","secret":"never-return-this"}')
    reader._calls['invoices.list'] = fail
    result = asyncio.run(chat('List PayPal invoices', treasurer=True, lang='en', reader=reader))
    call = result['paypal_tools']['calls'][0]
    assert call['debug_id'] == 'DEBUG-safe'
    assert call['status'] == 'error'
    assert call['http_status'] == 503
    assert call['latency_ms'] >= 0
    assert 'never-return-this' not in str(result)


def test_no_tools_rules_reply_has_turn_latency(reader):
    result = asyncio.run(chat('When is the money captured?', lang='en'))
    assert result['model_label'] == 'rules'
    assert result['latency_ms'] >= 0
    assert result['paypal_tools']['calls'] == []


def test_review_trace_is_returned_and_stored(reader):
    async def run():
        await ledger.get_ledger().insert_pledge_once({
            '_id': 'trace-pledge', 'milestone_id': 'dep-la-rochelle', 'status': 'authorized',
            'amount_eur': '5.00', 'order_id': 'ORDER-trace',
        })
        reader._calls['orders.get'] = lambda _: {'id': 'ORDER-trace'}
        result = await review('dep-la-rochelle', reader=reader, lang='en')
        assert result['model_label'] == 'rules'
        assert result['latency_ms'] >= 0
        assert result['paypal_tools']['calls'][0]['resource_id'] == 'ORDER-trace'
        stored = await ledger.get_ledger().get_milestone('dep-la-rochelle')
        assert stored['proposal']['latency_ms'] == result['latency_ms']
    asyncio.run(run())
