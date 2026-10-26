import json
import anthropic

client = anthropic.Anthropic()

# Single tool
tools = [
    {
        "name": "Create_calendar_event",
        "description": "Create a calendar event with attendees and optional recurrence",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start": {"type": "string", "format": "date-time"},
                "end": {"type": "string", "format": "date-time"},
                "attendees": {
                    "type": "array",
                    "items": {"type": "string", "format": "email"},
                },
                "recurrence": {
                    "type": "object",
                    "properties": {
                        "frequency": {"enum": ["daily", "weekly", "monthly"]},
                        "count": {"type": "integer", "minimum": 1},
                    },
                },
            },
            "required": ["title", "start", "end"],
        }
    }
]

# User Request
response = client.messages.create(
    model ="claude-sonnet-4-5",
    max_tokens = 1024,
    tools = tools,
    tool_choice = {"type": "auto", "disable_parallel_tool_use": True},
    messages = [
        {
            "role": "user",
            "content": "Schedule a 30 minute sync with alice@example.com and bob@example.com on Monday, 30, 2026 at 10am",
        }
    ],
)


print(f"stop_reason: {response.stop_reason}")

tool_use = next(block for block in response.content if block.type == "tool_use")
print(f"Tool: {tool_use.name}")
print(f"Input: {tool_use.input}")

result = {"event_id": "evt_123", "status": "created"}


#result block
followup = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=1024,
    tools=tools,
    tool_choice={"type": "auto", "disable_parallel_tool_use": True},
    messages=[
        {
            "role": "user",
            "content": "Schedule a 30-minute sync with alice@example.com and bob@example.com on Monday, March 30, 2026 at 10am.",
        },
        {"role": "assistant", "content": response.content},
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": json.dumps(result),
                }
            ],
        },
    ],
)

print(f"stop_reason: {followup.stop_reason}")
final_text = next(block for block in followup.content if block.type == "text")
print(final_text.text)
