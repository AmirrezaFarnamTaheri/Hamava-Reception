"""Pure typed schemas for model tool proposals; never an authorization grant."""
from typing import Annotated, Literal, Union
from pydantic import Field, TypeAdapter
from .schemas import BookingInput, CancelInput, HoldInput, RescheduleInput, StrictModel

class SlotArgs(StrictModel):
    provider_id: str = Field(min_length=1, max_length=60)
    service_id: str = Field(min_length=1, max_length=60)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class SlotsTool(StrictModel):
    tool: Literal["slots"]
    arguments: SlotArgs


class HoldTool(StrictModel):
    tool: Literal["hold"]
    arguments: HoldInput


class BookTool(StrictModel):
    tool: Literal["book"]
    arguments: BookingInput


class CancelArgs(CancelInput):
    appointment_id: str = Field(min_length=1, max_length=160)


class MoveArgs(RescheduleInput):
    appointment_id: str = Field(min_length=1, max_length=160)


class CancelTool(StrictModel):
    tool: Literal["cancel"]
    arguments: CancelArgs


class MoveTool(StrictModel):
    tool: Literal["reschedule"]
    arguments: MoveArgs


TOOLS = TypeAdapter(Annotated[Union[SlotsTool, HoldTool, BookTool, CancelTool, MoveTool], Field(discriminator="tool")])
TOOL_NAMES = ("slots", "hold", "book", "cancel", "reschedule")



class ModelToolEvent(StrictModel):
    event: Literal["tool_call"]
    request_id: str = Field(min_length=8, max_length=100)
    tool: str = Field(min_length=1, max_length=30)
    arguments: dict


def validate_model_tool_event(value):
    """Optional model adapters must emit a complete strict event before dispatch.

    No generative model is enabled by this function. Partial argument deltas are
    never executable and arbitrary assistant text cannot confirm a booking.
    """
    event = ModelToolEvent.model_validate(value)
    TOOLS.validate_python({"tool": event.tool, "arguments": event.arguments})
    return event
