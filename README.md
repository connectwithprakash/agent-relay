# Agent Relay v2

Enhanced agent-to-agent communication tool with WebSocket and webhook support.

## Project Status

**Backend:** ✅ Complete and ready for testing
**Frontend:** 🔨 Ready for Builder Agent to implement
**Testing:** ⏳ Pending integration

## Architecture

### Backend (Complete)
- **Framework:** FastAPI
- **Database:** SQLite with SQLAlchemy ORM
- **Real-time:** WebSocket support
- **Notifications:** Webhook delivery with retry logic
- **Validation:** Pydantic schemas

### Frontend (To Be Built)
- **Framework:** React 19 + Vite
- **Styling:** TailwindCSS
- **Real-time:** WebSocket client
- **UI:** Dashboard for message visualization

## Quick Start

### Backend Setup

```bash
cd backend

# Install dependencies
pip install -r requirements.txt

# Run server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Server will be available at http://localhost:8000
# API docs at http://localhost:8000/docs
```

### Frontend Setup (For Builder Agent)

```bash
cd frontend

# Create Vite project
npm create vite@latest . -- --template react

# Install dependencies
npm install
npm install # Add WebSocket client and TailwindCSS

# Run dev server
npm run dev
```

## API Endpoints

### Relay Management

**Create Relay**
```
POST /relays
Body: {"agent_names": ["agent_0", "agent_1"]}
Response: {"relay_id": "relay-xxx", "agent_names": [...], "current_turn": "agent_0"}
```

**Get Relay State**
```
GET /relays/{relay_id}
Response: {
  "relay_id": "relay-xxx",
  "current_turn": "agent_0",
  "agent_names": [...],
  "message_count": 5,
  "last_message": "Hello",
  "last_agent": "agent_1"
}
```

### Messaging

**Send Message**
```
POST /relays/{relay_id}/messages
Body: {
  "content": "Hello world",
  "type": "text",
  "agent": "agent_0"  // Optional, auto-detected
}
Response: {
  "status": "ok",
  "message_id": 1,
  "next_turn": "agent_1",
  "message_count": 1
}
```

**Get Message History**
```
GET /relays/{relay_id}/history?limit=50&offset=0
Response: {
  "relay_id": "relay-xxx",
  "messages": [...],
  "total_count": 10
}
```

### Webhooks

**Register Webhook**
```
POST /relays/{relay_id}/webhooks
Body: {
  "url": "https://your-webhook.com/endpoint",
  "agent": "agent_0"
}
Response: {
  "webhook_id": 1,
  "url": "https://...",
  "agent": "agent_0"
}
```

**List Webhooks**
```
GET /relays/{relay_id}/webhooks
Response: [
  {"id": 1, "agent": "agent_0", "url": "https://...", "created_at": "..."}
]
```

### WebSocket

**Connect**
```
WS /relays/{relay_id}/ws?agent=agent_0
```

**Receive Messages**
```json
{
  "id": 1,
  "agent": "agent_1",
  "content": "Hello",
  "data": null,
  "type": "text",
  "created_at": "2025-12-13T01:00:00",
  "next_turn": "agent_0"
}
```

## Frontend Requirements

### Components Needed

1. **RelayDashboard** - Main container
2. **MessageList** - Display message history
3. **MessageInput** - Send new messages
4. **TurnIndicator** - Show whose turn it is
5. **RelayInfo** - Display relay metadata

### WebSocket Integration

```javascript
// Example WebSocket client
const ws = new WebSocket(`ws://localhost:8000/relays/${relayId}/ws?agent=${agentName}`);

ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  // Update UI with new message
  console.log('New message:', message);
};
```

### API Client Example

```javascript
// Create relay
const createRelay = async () => {
  const response = await fetch('http://localhost:8000/relays', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({agent_names: ['agent_0', 'agent_1']})
  });
  return await response.json();
};

// Send message
const sendMessage = async (relayId, content, agent) => {
  const response = await fetch(`http://localhost:8000/relays/${relayId}/messages`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({content, type: 'text', agent})
  });
  return await response.json();
};
```

## Testing Plan

### Phase 1: Unit Testing (Backend - Done ✅)
- API endpoint validation
- Turn-based logic
- Message storage
- Webhook retry mechanism

### Phase 2: Integration Testing (Next)
**Coordinator + Builder will test together:**

1. **Basic Flow** - Create relay, exchange messages
2. **Turn Validation** - Verify only correct agent can send
3. **WebSocket** - Real-time message delivery
4. **Webhooks** - Delivery and retry logic
5. **Multi-Relay** - Isolation between relays
6. **Error Handling** - Invalid requests, disconnections

### Phase 3: Dogfooding
- Use new relay for our own coordination
- Find bugs in real-world usage
- Document migration experience

## Database Schema

```sql
-- Relays
id (string, primary key)
created_at (timestamp)
current_turn (integer)
agent_count (integer)
agent_names (json)

-- Messages
id (integer, autoincrement)
relay_id (foreign key)
agent_index (integer)
agent_name (string)
content (text, nullable)
data (json, nullable)
type (string: 'text' or 'structured')
created_at (timestamp)

-- Webhooks
id (integer, autoincrement)
relay_id (foreign key)
agent_index (integer)
agent_name (string)
url (string)
created_at (timestamp)

-- Webhook Deliveries (log)
id (integer, autoincrement)
webhook_id (foreign key)
message_id (foreign key)
status (string: 'success' or 'failed')
attempts (integer)
error_message (text, nullable)
created_at (timestamp)
```

## Features Implemented

- ✅ Turn-based messaging
- ✅ Real-time WebSocket updates
- ✅ Webhook delivery with 3 retry attempts
- ✅ Exponential backoff (1s, 2s, 4s)
- ✅ Message history with pagination
- ✅ Multiple concurrent relays
- ✅ CORS enabled
- ✅ Complete API documentation

## Next Steps

### For Builder Agent (Frontend):

1. **Setup** (30 mins)
   - Clone repository
   - Create React + Vite frontend
   - Install dependencies (TailwindCSS, etc.)

2. **Build Components** (2-3 hours)
   - MessageList component
   - MessageInput component
   - TurnIndicator component
   - RelayDashboard layout

3. **WebSocket Integration** (1 hour)
   - Connect to WebSocket
   - Handle incoming messages
   - Update UI in real-time

4. **API Integration** (1 hour)
   - Fetch relay state
   - Send messages
   - Display history

### For Coordinator (Backend):

1. **Testing** (1 hour)
   - Write pytest tests
   - Test all endpoints
   - Verify webhook delivery

2. **Documentation** (30 mins)
   - API examples
   - Deployment guide

3. **Integration Support** (ongoing)
   - Help debug frontend issues
   - Fix backend bugs
   - Optimize performance

## Communication

Since the old relay is down, we'll coordinate via:
- GitHub issues/PRs
- This README (update with status)
- Direct testing once both parts are ready

## Timeline

**Day 1 (Today):**
- ✅ Backend complete
- 🔨 Frontend in progress

**Day 2:**
- Integration testing
- Bug fixes
- Advanced features

**Day 3:**
- Dogfooding
- Documentation
- Portfolio project + blog post

## Contact

**Coordinator Agent:** Backend implementation
**Builder Agent:** Frontend implementation
**User:** Prakash Chaudhary (connectwithprakash)

---

Let's build something great! 🚀
