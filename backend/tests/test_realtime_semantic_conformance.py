"""Realtime outputs remain non-executable until final response success and schema checks."""
import pytest
from receptionist.providers import ProviderError
from receptionist.media.realtime_contract import RealtimeProposalStream


def events(name='slots', args='{"provider_id":"p1","service_id":"s1","date":"2026-10-24"}', status='completed'):
    return [
        {'type': 'session.created', 'session': {'id': 'synthetic'}},
        {'type': 'response.created', 'response': {'id': 'resp_1', 'status': 'in_progress'}},
        {'type': 'response.output_item.added', 'response_id': 'resp_1', 'item': {
            'id': 'item_1', 'type': 'function_call', 'call_id': 'call_1', 'name': name}},
        {'type': 'response.function_call_arguments.delta', 'response_id': 'resp_1', 'call_id': 'call_1', 'delta': args[:20]},
        {'type': 'response.function_call_arguments.delta', 'response_id': 'resp_1', 'call_id': 'call_1', 'delta': args[20:]},
        {'type': 'response.function_call_arguments.done', 'response_id': 'resp_1', 'call_id': 'call_1', 'arguments': args},
        {'type': 'response.output_item.done', 'response_id': 'resp_1', 'item': {
            'id': 'item_1', 'type': 'function_call', 'call_id': 'call_1', 'name': name,
            'status': 'completed', 'arguments': args}},
        {'type': 'response.done', 'response': {'id': 'resp_1', 'status': status}},
    ]


async def parse(sequence):
    async def feed():
        for item in sequence:
            yield item
    return [item async for item in RealtimeProposalStream().parse(feed(), request_id='realtime-req01')]


@pytest.mark.asyncio
async def test_realtime_complete_proposal_is_never_executable():
    out = await parse(events())
    assert out[0]['event'] == 'tool_proposal'
    assert out[0]['tool'] == 'slots' and out[0]['executable'] is False
    assert out[-1] == {'event':'completed', 'proposals': 1}


@pytest.mark.asyncio
async def test_realtime_output_item_done_is_not_enough():
    with pytest.raises(ProviderError, match='REALTIME_STREAM_INCOMPLETE'):
        await parse(events()[:-1])


@pytest.mark.asyncio
async def test_realtime_cancelled_final_response_never_dispatches():
    with pytest.raises(ProviderError, match='REALTIME_STREAM_INCOMPLETE'):
        await parse(events(status='cancelled'))


@pytest.mark.asyncio
async def test_realtime_rejects_malicious_tenant_argument():
    bad = '{"provider_id":"p1","service_id":"s1","date":"2026-10-24","tenant_id":"foreign"}'
    with pytest.raises(ProviderError, match='REALTIME_TOOL_REJECTED'):
        await parse(events(args=bad))


@pytest.mark.asyncio
async def test_realtime_rejects_mixed_response_ids():
    sequence = events()
    sequence[-1]['response']['id'] = 'different'
    with pytest.raises(ProviderError, match='REALTIME_RESPONSE_MISMATCH'):
        await parse(sequence)


@pytest.mark.asyncio
async def test_realtime_rejects_inconsistent_final_tool_arguments():
    sequence = events()
    sequence[-2]['item']['arguments'] = '{"wrong":"value"}'
    with pytest.raises(ProviderError, match='REALTIME_TOOL_REJECTED'):
        await parse(sequence)


@pytest.mark.asyncio
async def test_realtime_duplicate_output_item_is_rejected():
    sequence = events()
    sequence.insert(3, dict(sequence[2]))
    with pytest.raises(ProviderError, match='REALTIME_TOOL_REJECTED'):
        await parse(sequence)


@pytest.mark.asyncio
async def test_realtime_rejects_excessive_events():
    sequence = events()
    sequence[3:3] = [{'type':'rate_limits.updated'}] * 520
    with pytest.raises(ProviderError, match='REALTIME_STREAM_TOO_LONG'):
        await parse(sequence)
