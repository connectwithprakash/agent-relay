# Agent Communication Platforms: Competitive Research Report

**Date:** March 21, 2026
**Scope:** Leading agent communication platforms, protocols, and best practices (2025-2026)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [AgentWorkforce/relay Analysis](#1-agentworkforcerelay-analysis)
3. [Google A2A Protocol](#2-google-a2a-protocol)
4. [IBM ACP and ANP Protocols](#3-ibm-acp-and-anp-protocols)
5. [Multi-Agent Dashboard UX Patterns](#4-multi-agent-dashboard-ux-patterns)
6. [Turn-Based Protocol Research](#5-turn-based-protocol-research)
7. [Package Distribution Strategy](#6-package-distribution-strategy-pypinpm)
8. [Production Deployment Best Practices](#7-production-deployment-best-practices)
9. [Feature Gap Analysis](#8-feature-gap-analysis)
10. [Prioritized Recommendations](#9-prioritized-recommendations)

---

## Executive Summary

The agent communication landscape has matured significantly since mid-2025. Four major protocols now compete for adoption: Google's A2A, IBM's ACP, Anthropic's MCP, and the decentralized ANP. Meanwhile, AgentWorkforce/relay has emerged as the leading open-source implementation for real-time agent messaging, with a Slack-like communication model (channels, threads, DMs, reactions) that goes well beyond Agent Relay's current turn-based approach.

**Agent Relay's core differentiator** -- strict turn-based messaging that prevents collisions -- remains valuable but is now table stakes. The market expects: agent discovery, structured task lifecycles, multi-modal content, streaming, authentication, and observability. Agent Relay must evolve from a turn-based messaging tool into a protocol-aware communication platform to remain competitive.

**Top three priorities:**
1. Adopt A2A-compatible Agent Cards for discovery and capability advertisement
2. Add structured task lifecycle states (submitted, working, input-required, completed, failed)
3. Build a channel/thread model alongside the existing turn-based relay model

---

## 1. AgentWorkforce/relay Analysis

**Repository:** https://github.com/AgentWorkforce/relay
**Stack:** TypeScript (62.8%), Rust (19.8%), Python (8.8%)
**License:** Apache-2.0
**Commits:** 2,848+

### Features Agent Relay Lacks

| Feature | AgentWorkforce/relay | Agent Relay |
|---------|---------------------|-------------|
| Channel-based messaging | Channels, threads, DMs | Single relay only |
| Reactions & read receipts | Full support | Not supported |
| File attachments | Built-in | Not supported |
| Full-text search | Across message history | Not supported |
| Agent identity types | Agent, Human, System | Agent only |
| Multi-CLI support | Claude, Codex, Gemini, OpenCode, Cursor, VS Code, Windsurf, Zed | Claude Code (via MCP) |
| Plugin marketplace | `/plugin marketplace add` | Not available |
| Slash commands | `/relay-team`, `/relay-fanout`, `/relay-pipeline` | Not available |
| SDK languages | TypeScript, Python, MCP (identical interfaces) | Python only |
| Hosted service | Relaycast (hosted) + local mode | Self-hosted only |
| Sub-5ms latency claims | Yes | Not benchmarked |

### Dashboard (relay-dashboard)

AgentWorkforce's dashboard includes:
- **Agent status monitoring** -- live agent status via WebSocket
- **Communication interface** -- channels, DMs, broadcasts, @mentions
- **Terminal output streaming** -- live PTY output from agents for debugging
- **Decision queue** -- visual approval/rejection queue for human-in-the-loop
- **Fleet management** -- multi-project/workspace with aggregate statistics
- **System health metrics** -- throughput, session lifecycle, multi-server fleet stats
- **Light/dark mode** with compact display options
- **Three modes** -- full integration, proxy forwarding, standalone mock mode

### SDK Design

Their SDK provides:
- Agent spawning with custom model selection
- Channel subscription model (agents join channels)
- Readiness tracking (`waitForAgentReady`)
- Message interception via callbacks (`onMessageReceived`)
- System-level message dispatch
- Graceful shutdown mechanisms
- Bearer token authentication (workspace keys: `rk_live_*`, agent tokens: `at_live_*`)

### Key Takeaways

AgentWorkforce/relay has essentially built "headless Slack for AI agents" (their Relaycast product). They've moved past simple relay messaging into a full communication platform. Their plugin/skill marketplace and multi-CLI support give them significant distribution advantages.

---

## 2. Google A2A Protocol

**Specification:** https://a2a-protocol.org/latest/specification/
**Version:** 0.3.0+
**Partners:** 50+ (Atlassian, Salesforce, SAP, LangChain, MongoDB, PayPal)
**Foundation:** JSON-RPC 2.0, HTTP, SSE

### Agent Cards

Agent Cards are the protocol's discovery mechanism -- JSON metadata documents published by servers:

```
AgentCard {
  name, description, url
  provider: AgentProvider
  capabilities: { streaming, pushNotifications, extendedAgentCard }
  skills: AgentSkill[]
  securitySchemes: SecurityScheme[]
  extensions: AgentExtension[]
  signature: AgentCardSignature
}
```

**Lessons for Agent Relay:**
- Agents should self-describe their capabilities at a well-known URL
- Skills should be discrete, named capabilities with input/output descriptions
- Security schemes should be declared upfront, not bolted on
- Extended cards (authenticated) can reveal more capabilities to trusted clients

### Task Lifecycle States

A2A defines a rich state machine for tasks:

```
submitted -> working -> completed
                    -> failed
                    -> canceled
         -> input-required -> (client provides input) -> working
         -> auth-required -> (client authenticates) -> working
         -> rejected
```

Terminal states: `completed`, `canceled`, `rejected`, `failed` -- no further messages accepted.

**Lessons for Agent Relay:**
- Agent Relay's current model has no concept of task state -- messages just flow
- Adding task lifecycle would enable better orchestration and error handling
- The `input-required` state maps well to turn-based protocols (waiting for the other agent)
- Push notifications (webhooks) for state changes are already partially implemented

### Core JSON-RPC Methods

1. `SendMessage` / `SendStreamingMessage` -- initiate interaction
2. `GetTask` / `ListTasks` -- query task state with filtering/pagination
3. `CancelTask` -- request cancellation
4. `SubscribeToTask` -- streaming connection for updates
5. `CreateTaskPushNotificationConfig` -- register webhooks
6. `GetExtendedAgentCard` -- authenticated capability discovery

### Streaming Support

A2A uses Server-Sent Events (SSE) for real-time updates including:
- Status change notifications
- Artifact chunk delivery (partial results)
- Token-by-token streaming

### Authentication Model

Multi-scheme support: OAuth2, API keys, HTTP Basic, mTLS, OpenID Connect. Critically, A2A supports **in-task authorization** where agents can request credentials mid-processing via the `auth-required` state.

---

## 3. IBM ACP and ANP Protocols

### ACP (Agent Communication Protocol)

**Repository:** https://github.com/i-am-bee/acp
**Governance:** Linux Foundation
**Version:** 1.0.2

ACP takes a REST-native approach that differs from A2A's JSON-RPC model:
- **HTTP-native** -- works with cURL, Postman, standard HTTP clients
- **Multimodal messages** -- structured data, text, images, embeddings in message parts
- **SSE streaming** -- delta streams for incremental updates (tokens, trajectory)
- **Sync + async** -- both low-latency synchronous and long-running async modes
- **Agent registry** -- centralized discovery with agent metadata

**Key ACP patterns for Agent Relay:**
- REST is the right choice (Agent Relay already uses REST)
- Multimodal message parts would future-proof the protocol
- Delta streaming (incremental updates) is better than full-message delivery for long tasks
- A registry model could complement Agent Cards for local deployments

### ANP (Agent Network Protocol)

**Specification:** https://agent-network-protocol.com/
**Goal:** "The HTTP of the Agentic Web"

ANP's three-layer architecture is ambitious:
1. **Identity layer** -- W3C DID-based decentralized identity, end-to-end encryption
2. **Meta-protocol layer** -- runtime protocol negotiation between agents
3. **Application layer** -- Agent Description Protocol (ADP) for capability publishing

**Key ANP patterns:**
- Agent discovery via crawlable capability files at predictable URLs
- Decentralized identity without centralized registries
- Meta-protocol negotiation lets agents agree on communication format at runtime

**Relevance to Agent Relay:** ANP is forward-looking but has high negotiation overhead. Its discovery model (capability files at well-known URLs) is worth adopting. Full DID support is a long-term investment.

---

## 4. Multi-Agent Dashboard UX Patterns

### Current Best Practices (2025-2026)

**Separation of concerns** is the dominant pattern:
- **Conversation view** -- focused on message flow, not cluttered with metrics
- **Agent tree/graph view** -- visualizes agent interactions and dependencies
- **Metrics dashboard** -- system health, throughput, latency, cost
- **Decision queue** -- human-in-the-loop approval/rejection interface
- **Task progress view** -- per-task status with timeline visualization

**Problems with single-view dashboards:**
- Cramming agent trees, resource metrics, task progress, and approval prompts into interleaved chat creates cognitive overload
- Modern dashboards act as "cognitive collaborators" rather than passive displays

### Key UX Components to Adopt

1. **Agent status indicators** -- online/offline/busy/error per agent, real-time via WebSocket
2. **Thread visualization** -- message threading for parallel conversations within a relay
3. **Terminal/PTY streaming** -- show live agent output for debugging (AgentWorkforce does this)
4. **Decision queue panel** -- dedicated surface for human approvals
5. **Timeline view** -- horizontal timeline of task lifecycle with state transitions
6. **Cost tracker** -- token usage and API spend per relay/agent
7. **Searchable history** -- full-text search across all messages with filters

### Recommended Dashboard Architecture

```
+------------------+-------------------+------------------+
|   Agent Fleet    |   Active Relay    |   Task Status    |
|   (sidebar)      |   (main view)     |   (right panel)  |
|                  |                   |                  |
|  Agent 1: online |  Message flow     |  Task: working   |
|  Agent 2: busy   |  with threading   |  Artifacts: 2    |
|  Agent 3: error  |                   |  Duration: 5m    |
|                  |  [Decision Queue] |  Cost: $0.12     |
|  [+ New Relay]   |  [Input Area]     |  [Cancel] [Skip] |
+------------------+-------------------+------------------+
|              System Health Bar (latency, errors, uptime) |
+----------------------------------------------------------+
```

---

## 5. Turn-Based Protocol Research

### Current Landscape

Agent Relay's strict turn-based model is relatively unique in the protocol landscape. Most protocols (A2A, ACP, MCP) use request-response or streaming patterns rather than enforced turn order. This is both a strength (collision prevention) and a limitation (inflexibility).

### Recommended Protocol Improvements

**Turn Timeouts:**
- Implement configurable per-relay timeout (default: 5 minutes, configurable up to 24 hours)
- On timeout: auto-skip to next agent with a system message noting the timeout
- Expose timeout status via WebSocket so dashboards can show countdown timers
- A2A's task lifecycle suggests treating timeouts as state transitions, not errors

**Skip Mechanisms:**
- Allow the current-turn agent to explicitly skip their turn
- Allow relay administrators to force-skip via API
- Track skip counts per agent for observability
- Consider auto-skip after N consecutive timeouts

**Observer Mode:**
- Allow agents to join a relay as read-only observers
- Observers receive all messages via WebSocket but cannot send
- Useful for monitoring agents, logging services, and human supervisors
- A2A's `SubscribeToTask` is essentially an observer pattern

**Broadcast vs Round-Robin:**
- Current model is strictly round-robin between two (or more) agents
- Add broadcast mode: one agent sends, all others receive simultaneously
- Add selective addressing: `@agent_name` to direct messages within multi-agent relays
- AgentWorkforce/relay supports all three patterns (channels, DMs, broadcasts)

**Multi-Agent Turn Policies:**
- Round-robin (current): A -> B -> A -> B
- Free-form with collision prevention: any agent can send if no one is currently sending (mutex-based)
- Priority-based: higher-priority agents can interrupt
- Coordinator pattern: one agent manages turn allocation for others

### Research Gaps

There is limited academic research specifically on turn-based agent communication. Most multi-agent research focuses on:
- Message passing in distributed systems (no turn enforcement)
- Consensus protocols (blockchain-style)
- Auction/negotiation protocols (economic game theory)

The turn-based model is most similar to **token ring** network protocols, where a token circulates and only the token-holder can transmit. This is a well-understood pattern with known properties (fairness, bounded latency, no collisions).

---

## 6. Package Distribution Strategy (PyPI/npm)

### Market Context

- OpenAI Agents SDK: ~14.7M PyPI downloads/30 days
- MCP SDKs: ~97M monthly downloads across npm + PyPI
- Agent relay SDKs: early-stage adoption

### Minimum Feature Set for a Go-To Package

**Core (must-have for v1.0):**
1. Sync + async client with context managers
2. WebSocket listener with auto-reconnect
3. Pydantic models for all request/response types
4. Comprehensive error handling with typed exceptions
5. Retry logic with exponential backoff
6. Configurable timeouts
7. Token/API key authentication

**Discovery & Interoperability:**
8. Agent Card generation and parsing (A2A-compatible)
9. Health check endpoint client
10. Relay/task state machine helpers

**Developer Experience:**
11. Type hints throughout (py.typed marker)
12. Zero required dependencies beyond httpx and pydantic
13. CLI tool for quick testing (`agent-relay send`, `agent-relay status`)
14. Comprehensive docstrings and examples
15. Both `pip install agent-relay` and `npm install @agent-relay/sdk`

**Current Agent Relay SDK gaps:**
- No TypeScript/JavaScript SDK (AgentWorkforce has one)
- No CLI tool
- No Agent Card support
- No retry logic built into the SDK
- No authentication support
- v0.1.0 -- needs to reach v1.0 for credibility

### Package Quality Signals

What makes developers trust a package:
- Weekly download count above 1,000
- Test coverage badge (>80%)
- Active maintenance (commits in last 30 days)
- Semantic versioning
- Changelog
- Multiple contributors
- GitHub stars > 100
- Documentation site (not just README)
- Type stub availability
- Security audit passing

---

## 7. Production Deployment Best Practices

### Health Monitoring

**System Health Metrics:**
| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| API latency (p99) | <200ms | >500ms |
| WebSocket connection count | Tracked | >1000 or sudden drops |
| Message delivery rate | >99.9% | <99% |
| Database query time | <50ms | >200ms |
| Error rate | <0.1% | >1% |
| Uptime | 99.9% | Any downtime |

**Agent Behavior Metrics:**
| Metric | Purpose |
|--------|---------|
| Messages per relay per hour | Activity tracking |
| Turn timeout frequency | Agent health indicator |
| Average turn duration | Performance baseline |
| Relay completion rate | Success tracking |
| WebSocket reconnection rate | Connection stability |

### Observability Stack

**Recommended (2026):**
- **Metrics:** Prometheus + Grafana (open-source, proven at scale)
- **Tracing:** OpenTelemetry for distributed tracing across agent interactions
- **Logging:** Structured JSON logging with correlation IDs per relay
- **Alerting:** PagerDuty/Slack integration for critical alerts

**Agent-Specific Observability:**
- Log all prompts, responses, and tool calls for replay/debugging
- Track token usage and API spend per agent per relay
- Implement drift detection (unusual response patterns)
- Monitor for agent loops (repeated similar messages)

### Security Hardening

Based on 2025 audit findings (43% of early MCP servers had command injection vulnerabilities):

1. **Input validation** -- validate every parameter against JSON Schema before processing
2. **Rate limiting** -- per-agent and per-relay rate limits
3. **Authentication** -- API keys at minimum, OAuth2 for production
4. **Authorization** -- agents can only send messages in relays they belong to
5. **Secrets management** -- never log message content in production by default
6. **TLS everywhere** -- enforce HTTPS for all API and WebSocket connections

### Scaling Considerations

- **Database:** Migrate from SQLite to PostgreSQL for production (concurrent writes)
- **WebSocket:** Use Redis pub/sub for multi-instance WebSocket broadcasting
- **Message queue:** Consider adding a message queue (Redis Streams, NATS) for reliable delivery
- **Horizontal scaling:** Stateless API servers behind a load balancer
- **Message retention:** Configurable TTL for message history (cost management)

---

## 8. Feature Gap Analysis

### Critical Gaps (blocking adoption)

| Gap | Impact | Effort |
|-----|--------|--------|
| No agent discovery mechanism | Cannot integrate with A2A ecosystem | Medium |
| No task lifecycle states | Cannot track work completion | Medium |
| No authentication/authorization | Not production-safe | Medium |
| SQLite in production | Cannot scale beyond single instance | Low-Medium |
| No TypeScript SDK | Excludes majority of agent developers | Medium |
| No rate limiting | Vulnerable to abuse | Low |

### Important Gaps (limiting growth)

| Gap | Impact | Effort |
|-----|--------|--------|
| No channels/threads model | Limited to 1:1 relays | High |
| No file attachments | Cannot share artifacts | Medium |
| No message search | Poor developer experience | Medium |
| No observer mode | Cannot monitor without participating | Low |
| No turn timeouts | Stuck relays with no recovery | Low |
| No skip mechanism | Blocked agents block everyone | Low |
| No streaming support | Cannot show incremental progress | Medium |

### Nice-to-Have Gaps (competitive differentiation)

| Gap | Impact | Effort |
|-----|--------|--------|
| No plugin marketplace | Limited distribution | High |
| No hosted service | Requires self-hosting | Very High |
| No decision queue UI | No human-in-the-loop dashboard | Medium |
| No terminal streaming | Cannot debug agent output | Medium |
| No cost tracking | Cannot manage API spend | Low |
| No agent identity types (human/system) | Limited flexibility | Low |

---

## 9. Prioritized Recommendations

### Quick Wins (1-2 weeks each)

1. **Turn timeouts with auto-skip** -- configurable timeout per relay, system message on timeout, auto-advance to next agent. Prevents stuck relays, which is the most common pain point in turn-based systems.

2. **Skip turn API endpoint** -- `POST /relays/{id}/skip` allowing the current agent to skip. Minimal backend change, big UX improvement.

3. **Observer mode** -- add `role` field to relay participants (participant vs observer). Observers get WebSocket events but cannot send messages.

4. **Rate limiting middleware** -- per-IP and per-agent rate limits using a token bucket algorithm. Required for any production deployment.

5. **Health check endpoint** -- `GET /health` returning service status, database connectivity, WebSocket connection count, uptime. Standard for production systems.

6. **Agent identity types** -- add `agent_type` enum (agent, human, system) to participant model. Enables human-in-the-loop patterns.

### Medium-Term Investments (1-3 months)

7. **A2A-compatible Agent Cards** -- implement Agent Card generation at `/.well-known/agent.json`. Describe relay capabilities, supported skills, authentication requirements. This makes Agent Relay discoverable by any A2A-compatible system.

8. **Task lifecycle states** -- add a `Task` model with states (submitted, working, input-required, completed, failed, canceled). Link tasks to relays. Expose state transitions via WebSocket and webhooks.

9. **TypeScript SDK** -- publish `@agent-relay/sdk` on npm with identical API surface to the Python SDK. TypeScript is the dominant language for agent tooling.

10. **PostgreSQL migration** -- replace SQLite with PostgreSQL using the existing Alembic setup. Required for horizontal scaling and concurrent writes.

11. **Authentication system** -- API key-based auth at minimum. JWT tokens for agent identity. Support A2A security scheme declarations in Agent Cards.

12. **Message search** -- full-text search across relay message history with filters (agent, date range, content). Use PostgreSQL full-text search or integrate with a search index.

13. **Dashboard v2** -- redesign with three-panel layout: agent fleet sidebar, conversation main view, task status right panel. Add decision queue, agent status indicators, and system health bar.

### Long-Term Investments (3-6 months)

14. **Channel/thread model** -- add channels alongside relays. Channels support multiple agents with flexible turn policies. Threads allow parallel conversations within a channel. This brings parity with AgentWorkforce's Relaycast model.

15. **Streaming support** -- implement SSE for incremental message delivery. Support A2A's `SendStreamingMessage` pattern. Enable token-by-token display in the dashboard.

16. **Multi-modal message parts** -- support structured message content (text, files, JSON data, embedded UI). Align with A2A's Part model and ACP's multimodal messages.

17. **Production observability** -- integrate OpenTelemetry for distributed tracing. Add Prometheus metrics endpoint. Build Grafana dashboard template. Implement structured JSON logging with relay correlation IDs.

18. **Plugin/skill system** -- allow agents to register capabilities as discrete skills. Enable a marketplace model where relays can be created based on required skills.

19. **Hosted service** -- offer a managed Relaycast-like service at `api.agent-relay.dev` alongside the self-hosted option. This dramatically lowers the barrier to adoption.

20. **Multi-instance scaling** -- Redis pub/sub for WebSocket broadcasting across instances. Message queue for reliable delivery. Horizontal scaling behind a load balancer.

### Priority Matrix

```
                    HIGH IMPACT
                        |
   Turn Timeouts [QW]   |   Agent Cards [MT]
   Skip Turn [QW]       |   Task Lifecycle [MT]
   Rate Limiting [QW]   |   TypeScript SDK [MT]
   Health Check [QW]    |   Auth System [MT]
                        |
  LOW EFFORT -----------+----------- HIGH EFFORT
                        |
   Observer Mode [QW]   |   Channels/Threads [LT]
   Agent Types [QW]     |   Hosted Service [LT]
   Cost Tracking [QW]   |   Plugin System [LT]
                        |
                    LOW IMPACT

  [QW] = Quick Win    [MT] = Medium-Term    [LT] = Long-Term
```

---

## Appendix: Protocol Comparison Matrix

| Feature | Agent Relay | A2A | ACP | MCP | ANP | AgentWorkforce |
|---------|-------------|-----|-----|-----|-----|----------------|
| Discovery | None | Agent Cards | Registry | Manual/static | DID + crawl | Marketplace |
| Transport | REST + WS | JSON-RPC + SSE | REST + SSE | JSON-RPC | Meta-negotiation | REST + WS |
| Auth | None | Multi-scheme | RBAC + DID | Per-server | DID-based | Bearer tokens |
| Streaming | WebSocket only | SSE | SSE (delta) | N/A | Negotiated | WebSocket |
| Task states | None | 7 states | Sync + async | N/A | N/A | Channel-based |
| Turn control | Strict | None | None | Req-response | Negotiated | Flexible |
| Multi-modal | Text only | Text + file + data | Text + image + data | Tool results | JSON-LD | Text + file |
| Observability | Basic logs | OpenTelemetry | Framework-specific | Per-server | N/A | Fleet metrics |
| SDKs | Python | Python, TypeScript | Python, TypeScript | Python, TypeScript | Python | TS, Python, MCP |
| Maturity | v0.1 | v0.3 | v1.0.2 | Stable | Early | Production |

---

## Sources

- [AgentWorkforce/relay - GitHub](https://github.com/AgentWorkforce/relay)
- [AgentWorkforce/relay-dashboard - GitHub](https://github.com/AgentWorkforce/relay-dashboard)
- [AgentWorkforce/relaycast - GitHub](https://github.com/AgentWorkforce/relaycast)
- [Google A2A Protocol Announcement](https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/)
- [A2A Protocol Specification](https://a2a-protocol.org/latest/specification/)
- [A2A Protocol Upgrade Blog](https://cloud.google.com/blog/products/ai-machine-learning/agent2agent-protocol-is-getting-an-upgrade)
- [IBM ACP - GitHub](https://github.com/i-am-bee/acp)
- [IBM ACP Overview](https://www.ibm.com/think/topics/agent-communication-protocol)
- [Agent Network Protocol - GitHub](https://github.com/agent-network-protocol/AgentNetworkProtocol)
- [ANP White Paper](https://agent-network-protocol.com/specs/white-paper.html)
- [Survey of Agent Interoperability Protocols (arxiv)](https://arxiv.org/html/2505.02279v1)
- [AI Agent Monitoring Best Practices - UptimeRobot](https://uptimerobot.com/knowledge-hub/monitoring/ai-agent-monitoring-best-practices-tools-and-metrics/)
- [A2A Protocol Explained - Galileo](https://galileo.ai/blog/google-agent2agent-a2a-protocol-guide)
- [A2A Protocol Explained - IBM](https://www.ibm.com/think/topics/agent2agent-protocol)
- [Top AI Agent Protocols 2026 - GetStream](https://getstream.io/blog/ai-agent-protocols/)
- [Agent Communication Protocols - DigitalOcean](https://www.digitalocean.com/community/tutorials/agent-communication-protocols-explained)
- [AWS Agent-to-Agent Protocols](https://docs.aws.amazon.com/prescriptive-guidance/latest/agentic-ai-frameworks/agent-to-agent-protocols.html)
- [AI Agent Observability Tools 2026](https://research.aimultiple.com/agentic-monitoring/)
- [Best npm Packages for AI Agents 2026](https://www.pkgpulse.com/blog/best-npm-packages-ai-agents-2026)
- [OpenAI Agents SDK - PyPI](https://pypi.org/project/openai-agents/)
- [ACP Technical Overview - WorkOS](https://workos.com/blog/ibm-agent-communication-protocol-acp)
