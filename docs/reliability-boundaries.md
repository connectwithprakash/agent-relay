# Reliability boundaries

## Guaranteed today

The relay command path is transactional: an authenticated participant's message, turn transition, and relay version advance commit together. Clients can provide `expected_version`; stale commands receive HTTP 409.

Pairing invitations are creator-issued, target one approved participant, expire, and can be redeemed once.

## Best effort today

WebSocket broadcasts and webhook triggers are post-commit, in-process notifications. A process crash after command commit may lose a notification. Consumers must reconcile from relay history and idempotency keys.

## Required before guaranteed external delivery

A transactional outbox, leased worker, retry/backoff policy, and dead-letter state are required before webhooks can be described as durable delivery.
