# Reliability boundaries

## Guaranteed today

The relay command path is transactional: an authenticated participant's message, turn transition, and relay version advance commit together. Clients can provide `expected_version`; stale commands receive HTTP 409.

Pairing invitations are creator-issued, target one approved participant, expire, and can be redeemed once.

Webhook events are inserted into a durable outbox in the same transaction as the message and turn transition. A leased asynchronous dispatcher retries connection errors, HTTP 408/429 responses, and 5xx responses with exponential backoff. Abandoned leases are reclaimed after restart, and exhausted or permanent failures remain visible in the `dead` state. Delivery is at least once: receivers should deduplicate with the `X-Agent-Relay-Event-ID` header.

## Best effort today

WebSocket broadcasts remain post-commit, in-process notifications. A process crash after command commit may lose a WebSocket notification. Consumers should still reconcile authoritative state from relay history after disconnects.

No webhook system can guarantee that an unavailable receiver eventually responds successfully. Agent Relay guarantees durable at-least-once attempts through the configured retry limit; receivers own event-id deduplication, and operators own inspection/replay of dead-letter rows.
