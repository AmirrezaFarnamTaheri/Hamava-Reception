"""Offline semantic conformance for Realtime tool-response events.

This parses verified *server* events; it is not a transport, model provider,
OpenAI Realtime-compatible endpoint, or tool authorization gateway. No audio,
partial assistant output, or model tool fragment can mutate a patient record.
"""
from __future__ import annotations

import json
import re
from collections.abc import AsyncIterable

from ..providers import ProviderError
from ..tool_contract import validate_model_tool_event

_IDENTIFIER = re.compile(r"^[a-zA-Z0-9_-]{1,100}$")
_REQUEST = re.compile(r"^[a-zA-Z0-9_-]{8,100}$")


class RealtimeProposalStream:
    """Final-only tool proposals across response-scoped Realtime events."""

    async def parse(self, events: AsyncIterable[dict], *, request_id: str):
        if not _REQUEST.fullmatch(request_id):
            raise ProviderError("REALTIME_INVALID_REQUEST_ID")
        response_id: str | None = None
        calls: dict[str, dict] = {}
        count = 0
        total_bytes = 0
        async for event in events:
            count += 1
            if not isinstance(event, dict) or count > 512:
                raise ProviderError("REALTIME_STREAM_TOO_LONG")
            total_bytes += len(json.dumps(event, ensure_ascii=True))
            if total_bytes > 131072:
                raise ProviderError("REALTIME_STREAM_TOO_LONG")
            kind = event.get("type")
            if kind == "error":
                raise ProviderError("REALTIME_STREAM_INCOMPLETE")
            if kind == "response.created":
                response = event.get("response")
                if response_id is not None or not isinstance(response, dict) or not _IDENTIFIER.fullmatch(str(response.get("id", ""))):
                    raise ProviderError("REALTIME_RESPONSE_MISMATCH")
                response_id = response["id"]
                continue
            if kind == "response.done":
                response = event.get("response")
                if not isinstance(response, dict) or response_id is None or response.get("id") != response_id:
                    raise ProviderError("REALTIME_RESPONSE_MISMATCH")
                if response.get("status") != "completed":
                    raise ProviderError("REALTIME_STREAM_INCOMPLETE")
                proposals = []
                for call_id, call in calls.items():
                    if call["done"] is not True or call["arguments"] is None or call["item_done"] is not True:
                        raise ProviderError("REALTIME_TOOL_INCOMPLETE")
                    try:
                        validated = validate_model_tool_event({
                            "event": "tool_call", "request_id": request_id,
                            "tool": call["name"], "arguments": json.loads(call["arguments"])
                        })
                    except Exception as exc:
                        raise ProviderError("REALTIME_TOOL_REJECTED") from exc
                    proposals.append({"event": "tool_proposal", "request_id": request_id,
                                      "tool": validated.tool, "arguments": validated.arguments,
                                      "call_id": call_id, "executable": False})
                for proposal in proposals:
                    yield proposal
                yield {"event": "completed", "proposals": len(proposals)}
                return
            if kind not in {"response.output_item.added", "response.function_call_arguments.delta",
                            "response.function_call_arguments.done", "response.output_item.done"}:
                continue
            if response_id is None or (event.get("response_id") not in {None, response_id}):
                raise ProviderError("REALTIME_RESPONSE_MISMATCH")
            if kind in {"response.output_item.added", "response.output_item.done"}:
                item = event.get("item")
                if not isinstance(item, dict):
                    raise ProviderError("REALTIME_TOOL_REJECTED")
                if item.get("type") != "function_call":
                    continue
                call_id = item.get("call_id")
                item_id = item.get("id")
                name = item.get("name")
                if not all(isinstance(v, str) and _IDENTIFIER.fullmatch(v) for v in (call_id, item_id, name)):
                    raise ProviderError("REALTIME_TOOL_REJECTED")
                if kind == "response.output_item.added":
                    if call_id in calls or len(calls) >= 8:
                        raise ProviderError("REALTIME_TOOL_REJECTED")
                    calls[call_id] = {"id": item_id, "name": name, "delta": "", "arguments": None,
                                      "done": False, "item_done": False}
                else:
                    call = calls.get(call_id)
                    if (not call or call["item_done"] or not call["done"] or call["id"] != item_id
                            or call["name"] != name or item.get("status") != "completed"
                            or item.get("arguments") != call["arguments"]):
                        raise ProviderError("REALTIME_TOOL_REJECTED")
                    call["item_done"] = True
                continue
            call_id = event.get("call_id")
            call = calls.get(call_id)
            if not call or call["done"]:
                raise ProviderError("REALTIME_TOOL_REJECTED")
            if kind.endswith(".delta"):
                delta = event.get("delta")
                if not isinstance(delta, str) or len(delta) > 8192 - len(call["delta"]):
                    raise ProviderError("REALTIME_TOOL_REJECTED")
                call["delta"] += delta
            else:
                arguments = event.get("arguments")
                if (not isinstance(arguments, str) or len(arguments) > 8192
                        or (call["delta"] and arguments != call["delta"])):
                    raise ProviderError("REALTIME_TOOL_REJECTED")
                call["arguments"] = arguments
                call["done"] = True
        raise ProviderError("REALTIME_STREAM_INCOMPLETE")
