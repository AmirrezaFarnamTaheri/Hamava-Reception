"""Streaming contract acceptance: partials are advisory and tool deltas inert."""
import asyncio
import json

import httpx
import pytest

from receptionist.providers import ProviderError
from receptionist.media.streaming import DeepgramRealtimeSTT, GatewayPCMStream, ResponsesToolStream


class WebSocketFixture:
    def __init__(self, events):
        self.events = events
        self.sent = []
        self.closed = False

    async def send(self, value):
        self.sent.append(value)

    async def close(self):
        self.closed = True

    async def __aiter__(self):
        for item in self.events:
            await asyncio.sleep(0)
            yield json.dumps(item)


async def test_deepgram_partial_final_and_split_final_segments(monkeypatch):
    monkeypatch.setenv('SPEECH_PROCESSOR_APPROVED', 'true')
    monkeypatch.setenv('SPEECH_STREAMING_APPROVED', 'true')
    monkeypatch.setenv('APPROVED_PROVIDER_HOSTS', 'api.deepgram.com')
    monkeypatch.setenv('STT_APPROVED_KEYTERMS_JSON', '["doctor"]')
    packets = [
        {'type': 'Results', 'is_final': False, 'speech_final': False, 'channel': {'alternatives': [{'transcript': 'hello may'}]}},
        {'type': 'Results', 'is_final': True, 'speech_final': False, 'channel': {'alternatives': [{'transcript': 'hello'}]}},
        {'type': 'Results', 'is_final': False, 'speech_final': False, 'channel': {'alternatives': [{'transcript': 'the doctor'}]}},
        {'type': 'Results', 'is_final': True, 'speech_final': True, 'channel': {'alternatives': [{'transcript': 'the doctor'}]}},
    ]
    socket = WebSocketFixture(packets)
    arguments = {}
    async def connect(url, **kw):
        arguments.update(url=url, **kw)
        return socket
    async def audio():
        for _ in range(3):
            yield b'\0' * 640
    events = [item async for item in DeepgramRealtimeSTT('fake-key', connect=connect).events(audio(), keyterms=['doctor'])]
    assert [item['event'] for item in events] == ['partial', 'partial', 'final']
    assert events[-1]['text'] == 'hello the doctor'
    assert events[-1]['audio_seconds'] == pytest.approx(.06)
    assert events[-1]['final'] is True and events[0]['final'] is False
    assert socket.closed and len([a for a in socket.sent if isinstance(a, bytes)]) == 3
    assert 'interim_results=true' in arguments['url'] and 'language=fa' in arguments['url']
    assert 'fake-key' not in arguments['url']


async def test_deepgram_refuses_unapproved_processor_without_opening(monkeypatch):
    monkeypatch.delenv('SPEECH_STREAMING_APPROVED', raising=False)
    called = []
    async def connect(*args, **kwargs):
        called.append(True)
    async def audio():
        yield b'\0'*640
    with pytest.raises(ProviderError, match='STREAMING_NOT_APPROVED'):
        async for _ in DeepgramRealtimeSTT('test', connect=connect).events(audio()):
            pass
    assert not called


async def test_deepgram_no_complete_utterance_cannot_be_confirmed(monkeypatch):
    monkeypatch.setenv('SPEECH_PROCESSOR_APPROVED', 'true')
    monkeypatch.setenv('SPEECH_STREAMING_APPROVED', 'true')
    monkeypatch.setenv('APPROVED_PROVIDER_HOSTS', 'api.deepgram.com')
    socket = WebSocketFixture([{'type': 'Results', 'is_final':False,'speech_final':False,
                               'channel':{'alternatives':[{'transcript':'maybe a date'}]}}])
    async def connect(*args, **kwargs):
        return socket
    async def audio():
        yield b'\0'*640
    with pytest.raises(ProviderError, match='STT_STREAM_INCOMPLETE'):
        async for event in DeepgramRealtimeSTT('test', connect=connect).events(audio()):
            assert event['event'] == 'partial'
    assert socket.closed


async def test_native_tts_emits_before_complete_response_and_rejects_truncation(monkeypatch):
    monkeypatch.setenv('SPEECH_PROCESSOR_APPROVED', 'true')
    monkeypatch.setenv('SPEECH_STREAMING_APPROVED', 'true')
    monkeypatch.setenv('APPROVED_PROVIDER_HOSTS', 'speech.example.test')
    from httpx import AsyncByteStream
    class MediaBytes(AsyncByteStream):
        async def __aiter__(self):
            yield b'\0'*800
            yield b'\0'*480
        async def aclose(self):
            pass
    def handler(request):
        assert request.url.path == '/synthesize/stream'
        return httpx.Response(200, stream=MediaBytes(), headers={'content-type': 'application/octet-stream',
            'x-audio-format':'pcm_s16le','x-audio-sample-rate':'16000','x-audio-channels':'1','x-audio-total-bytes':'1280'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        events = [e async for e in GatewayPCMStream('https://speech.example.test', 'test', client).events('hello')]
    assert [(e['event'],e['sequence']) for e in events] == [('audio',0),('audio',1),('end',2)]
    assert events[0]['buffered'] is False and len(events[0]['pcm16']) == 640


async def test_model_stream_waits_for_completed_response_before_proposing_tool():
    async def events():
        for item in [
            {'type':'response.output_item.added','item':{'id':'item-1','type':'function_call','name':'slots','call_id':'call-1'}},
            {'type':'response.function_call_arguments.delta','item_id':'item-1','delta':'{"provider_id":"p",'},
            {'type':'response.function_call_arguments.done','item_id':'item-1',
             'arguments':'{"provider_id":"p","service_id":"s","date":"2026-10-24"}'},
            {'type':'response.completed','response':{'status':'completed'}},
        ]:
            yield item
    results = [item async for item in ResponsesToolStream().parse(events(), request_id='req-12345678')]
    assert [r['event'] for r in results] == ['tool_proposal', 'completed']
    assert results[0]['tool'] == 'slots' and results[0]['arguments']['date'] == '2026-10-24'
    assert results[0]['executable'] is False


async def test_model_stream_incomplete_response_never_dispatches_tool():
    async def events():
        yield {'type':'response.output_item.added','item':{'id':'item-1','type':'function_call','name':'book','call_id':'call-1'}}
        yield {'type':'response.function_call_arguments.done','item_id':'item-1','arguments':'{}'}
        yield {'type':'response.incomplete','response':{'status':'incomplete'}}
    with pytest.raises(ProviderError, match='MODEL_STREAM_INCOMPLETE'):
        assert [item async for item in ResponsesToolStream().parse(events(),request_id='req-12345678')] == []


async def test_model_stream_rejects_model_provided_tenant_authority():
    async def events():
        yield {'type':'response.output_item.added','item':{'id':'item','type':'function_call','name':'slots'}}
        yield {'type':'response.function_call_arguments.done','item_id':'item',
               'arguments':'{"provider_id":"p","service_id":"s","date":"2026-10-24","tenant_id":"other"}'}
        yield {'type':'response.completed','response':{'status':'completed'}}
    with pytest.raises(ProviderError, match='MODEL_TOOL_REJECTED'):
        async for _ in ResponsesToolStream().parse(events(), request_id='req-12345678'):
            pass


async def test_streaming_stt_refuses_unapproved_dynamic_keyterms(monkeypatch):
    monkeypatch.setenv('SPEECH_PROCESSOR_APPROVED', 'true')
    monkeypatch.setenv('SPEECH_STREAMING_APPROVED', 'true')
    monkeypatch.setenv('APPROVED_PROVIDER_HOSTS', 'api.deepgram.com')
    monkeypatch.setenv('STT_APPROVED_KEYTERMS_JSON', '["doctor"]')
    called = []
    async def connect(*args, **kwargs):
        called.append(True)
    async def audio():
        yield b'\0'*640
    with pytest.raises(ProviderError, match='STT_KEYTERM_NOT_APPROVED'):
        async for _ in DeepgramRealtimeSTT('key',connect=connect).events(audio(),keyterms=['09123456789']):
            pass
    assert not called


async def test_native_tts_truncated_pcm_does_not_emit_end(monkeypatch):
    monkeypatch.setenv('SPEECH_PROCESSOR_APPROVED','true')
    monkeypatch.setenv('SPEECH_STREAMING_APPROVED','true')
    monkeypatch.setenv('APPROVED_PROVIDER_HOSTS','speech.example.test')
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200,
        content=b'\0'*641, headers={'content-type':'application/octet-stream',
        'x-audio-format':'pcm_s16le','x-audio-sample-rate':'16000','x-audio-channels':'1','x-audio-total-bytes':'640'}))) as client:
        seen=[]
        with pytest.raises(ProviderError,match='TTS_STREAM_TRUNCATED'):
            async for event in GatewayPCMStream('https://speech.example.test','test',client).events('hello'):
                seen.append(event)
    assert [x['event'] for x in seen] == ['audio']


async def test_model_sse_request_blocks_unapproved_provider(monkeypatch):
    monkeypatch.delenv('MODEL_STREAMING_APPROVED',raising=False)
    seen=[]
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: (seen.append(True),httpx.Response(200))[1])) as client:
        with pytest.raises(ProviderError,match='MODEL_STREAMING_NOT_APPROVED'):
            async for _ in ResponsesToolStream().request(prompt='hello',model='test',tools=[],client=client,request_id='req-12345678'):
                pass
    assert not seen


async def test_stt_rejects_malformed_provider_payload_as_bounded_provider_error(monkeypatch):
    monkeypatch.setenv('SPEECH_PROCESSOR_APPROVED','true')
    monkeypatch.setenv('SPEECH_STREAMING_APPROVED','true')
    monkeypatch.setenv('APPROVED_PROVIDER_HOSTS','api.deepgram.com')
    async def connect(*args,**kwargs):
        return WebSocketFixture([{'type':'Results','channel':None,'is_final':True}])
    async def audio():
        yield b'\0'*640
    with pytest.raises(ProviderError,match='STT_INVALID_EVENT'):
        async for _ in DeepgramRealtimeSTT('test',connect=connect).events(audio()):
            pass


async def test_stt_rejects_identifier_like_keyterm_even_when_configured(monkeypatch):
    monkeypatch.setenv('SPEECH_PROCESSOR_APPROVED','true')
    monkeypatch.setenv('SPEECH_STREAMING_APPROVED','true')
    monkeypatch.setenv('APPROVED_PROVIDER_HOSTS','api.deepgram.com')
    monkeypatch.setenv('STT_APPROVED_KEYTERMS_JSON','["09123456789"]')
    called=[]
    async def connect(*args,**kwargs):
        called.append(True)
    async def audio():
        yield b'\0'*640
    with pytest.raises(ProviderError,match='STT_KEYTERM_NOT_APPROVED'):
        async for _ in DeepgramRealtimeSTT('test',connect=connect).events(audio(),keyterms=['09123456789']):
            pass
    assert not called


async def test_tts_declared_content_length_mismatch_is_not_complete(monkeypatch):
    monkeypatch.setenv('SPEECH_PROCESSOR_APPROVED','true')
    monkeypatch.setenv('SPEECH_STREAMING_APPROVED','true')
    monkeypatch.setenv('APPROVED_PROVIDER_HOSTS','speech.example.test')
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200,content=b'\0'*640,headers={
        'Content-Type':'application/octet-stream','X-Audio-Format':'pcm_s16le','X-Audio-Sample-Rate':'16000',
        'X-Audio-Channels':'1','X-Audio-Total-Bytes':'1280'}))) as client:
        with pytest.raises(ProviderError,match='TTS_STREAM_TRUNCATED'):
            async for _ in GatewayPCMStream('https://speech.example.test','fake',client).events('test'):
                pass
