const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

/**
 * Get relay state
 */
export const getRelay = async (relayId, ownerId = null) => {
  const url = new URL(`${API_BASE_URL}/relays/${relayId}`);
  if (ownerId) {
    url.searchParams.append('owner_id', ownerId);
  }
  const response = await fetch(url);
  if (!response.ok) {
    if (response.status === 403) {
      throw new Error('This relay is private. Access denied.');
    }
    throw new Error(`Failed to fetch relay: ${response.statusText}`);
  }
  return await response.json();
};

/**
 * Create a new relay
 */
export const createRelay = async (agentNames, ownerId = null, isPublic = false) => {
  const response = await fetch(`${API_BASE_URL}/relays`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      agent_names: agentNames,
      owner_id: ownerId,
      is_public: isPublic
    }),
  });
  if (!response.ok) throw new Error(`Failed to create relay: ${response.statusText}`);
  return await response.json();
};

/**
 * Send a message to a relay
 */
export const sendMessage = async (relayId, content, agent, apiKey = null) => {
  const headers = { 'Content-Type': 'application/json' };
  if (apiKey) {
    headers['Authorization'] = `Bearer ${apiKey}`;
  } else {
    // Try to get from localStorage
    const { getApiKey } = await import('./auth.js');
    const storedKey = getApiKey(relayId);
    if (storedKey) headers['Authorization'] = `Bearer ${storedKey}`;
  }
  const response = await fetch(`${API_BASE_URL}/relays/${relayId}/messages`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ content, type: 'text', agent }),
  });
  if (!response.ok) throw new Error(`Failed to send message: ${response.statusText}`);
  return await response.json();
};

/**
 * Get message history for a relay
 */
export const getHistory = async (relayId, limit = 50, offset = 0) => {
  const response = await fetch(
    `${API_BASE_URL}/relays/${relayId}/history?limit=${limit}&offset=${offset}`
  );
  if (!response.ok) throw new Error(`Failed to fetch history: ${response.statusText}`);
  return await response.json();
};

/**
 * Update relay privacy setting
 */
export const updateRelayPrivacy = async (relayId, isPublic, ownerId) => {
  const response = await fetch(`${API_BASE_URL}/relays/${relayId}/privacy`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ is_public: isPublic, owner_id: ownerId }),
  });
  if (!response.ok) throw new Error(`Failed to update privacy: ${response.statusText}`);
  return await response.json();
};

/**
 * List public relays
 */
export const listPublicRelays = async (limit = 20, offset = 0) => {
  const response = await fetch(`${API_BASE_URL}/relays?limit=${limit}&offset=${offset}`);
  if (!response.ok) throw new Error(`Failed to fetch relays: ${response.statusText}`);
  return await response.json();
};

/**
 * Create WebSocket connection for real-time updates
 */
export const connectWebSocket = (relayId, agent, onMessage) => {
  const wsUrl = API_BASE_URL.replace('https://', 'wss://').replace('http://', 'ws://');
  const ws = new WebSocket(`${wsUrl}/relays/${relayId}/ws?agent=${agent}`);

  ws.onopen = () => console.log(`WebSocket connected for agent: ${agent}`);
  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    onMessage(message);
  };
  ws.onerror = (error) => console.error('WebSocket error:', error);
  ws.onclose = () => console.log('WebSocket disconnected');

  return ws;
};
