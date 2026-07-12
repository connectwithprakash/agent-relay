# Agent Relay Python SDK

Python SDK for [Agent Relay](https://github.com/prakash/agent-relay) - turn-based agent-to-agent communication.

## Installation

```bash
pip install agent-relay
```

Or install from source:

```bash
cd sdk
pip install -e .
```

## Quick Start

### Synchronous Client

```python
from agent_relay import AgentRelayClient

with AgentRelayClient("http://localhost:8000") as client:
    # Create a relay with two agents
    relay = client.create_relay(["alice", "bob"])
    print(f"Relay ID: {relay.relay_id}")

    # Send a message (must be alice's turn first)
    result = client.send_message(relay.relay_id, "Hello Bob!", "alice")
    print(f"Next turn: {result.next_turn}")

    # Read message history
    messages = client.get_history(relay.relay_id)
    for msg in messages:
        print(f"  {msg.agent}: {msg.content}")
```

## Error Handling

```python
from agent_relay import (
    AgentRelayClient,
    NotYourTurnError,
    RelayNotFoundError,
    AuthenticationError,
)

with AgentRelayClient() as client:
    try:
        client.send_message("relay-id", "hello", "bob")
    except NotYourTurnError:
        print("Wait for your turn!")
    except RelayNotFoundError:
        print("Relay does not exist")
    except AuthenticationError:
        print("Invalid API key")
```

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```
