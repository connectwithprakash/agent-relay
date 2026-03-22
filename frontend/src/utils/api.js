const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

/**
 * Handle fetch errors with specific status code messages
 */
const handleResponse = async (response, action) => {
  if (response.ok) return await response.json();
  switch (response.status) {
    case 400: throw new Error(`Bad request: ${(await response.json().catch(() => ({}))).detail || response.statusText}`);
    case 403: throw new Error('Access denied. This relay may be private.');
    case 404: throw new Error('Not found. The relay or resource may have been deleted.');
    case 409: throw new Error('Conflict. It may not be your turn to send.');
    case 429: throw new Error('Too many requests. Please wait and try again.');
    default: throw new Error(`Failed to ${action}: ${response.statusText}`);
  }
};

/**
 * Wrap fetch with network error handling
 */
const safeFetch = async (url, options) => {
  try {
    return await fetch(url, options);
  } catch (err) {
    if (err.name === 'TypeError') {
      throw new Error('Network error. Check your connection and try again.');
    }
    throw err;
  }
};

/**
 * Build auth headers for a relay using its stored token
 */
const authHeaders = (relayId) => {
  const { getToken } = require('./auth.js');
  const token = getToken(relayId);
  return token ? { 'Authorization': `Bearer ${token}` } : {};
};

/**
 * Get relay state
 */
export const getRelay = async (relayId, ownerId = null) => {
  const url = new URL(`${API_BASE_URL}/relays/${relayId}`);
  if (ownerId) {
    url.searchParams.append('owner_id', ownerId);
  }
  const response = await safeFetch(url);
  return handleResponse(response, 'fetch relay');
};

/**
 * Create a new relay
 */
export const createRelay = async (agentNames, ownerId = null, isPublic = false, options = {}) => {
  const body = {
    agent_names: agentNames,
    owner_id: ownerId,
    is_public: isPublic,
  };
  if (options.description) body.description = options.description;
  if (options.max_agents) body.max_agents = options.max_agents;
  if (options.min_agents) body.min_agents = options.min_agents;
  const response = await safeFetch(`${API_BASE_URL}/relays`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return handleResponse(response, 'create relay');
};

/**
 * Look up a relay by its short join code
 */
export const getRelayByCode = async (joinCode) => {
  const response = await safeFetch(`${API_BASE_URL}/relays/code/${joinCode.toUpperCase()}`);
  return handleResponse(response, 'look up join code');
};

/**
 * Join a relay using a short join code
 */
export const joinByCode = async (joinCode, agentName) => {
  const url = new URL(`${API_BASE_URL}/relays/join/${joinCode.toUpperCase()}`);
  url.searchParams.append('agent_name', agentName);
  const response = await safeFetch(url, { method: 'POST' });
  return handleResponse(response, 'join relay');
};

/**
 * Send a message to a relay
 */
export const sendMessage = async (relayId, content, agent = null, token = null) => {
  const headers = { 'Content-Type': 'application/json' };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  } else {
    // Try to get from localStorage
    const { getToken } = await import('./auth.js');
    const storedToken = getToken(relayId);
    if (storedToken) headers['Authorization'] = `Bearer ${storedToken}`;
  }
  const body = { content, type: 'text' };
  // Agent name comes from token on the server side, but include if provided for fallback
  if (agent) body.agent = agent;
  const response = await safeFetch(`${API_BASE_URL}/relays/${relayId}/messages`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  return handleResponse(response, 'send message');
};

/**
 * Get message history for a relay
 */
export const getHistory = async (relayId, limit = 50, offset = 0) => {
  const response = await safeFetch(
    `${API_BASE_URL}/relays/${relayId}/history?limit=${limit}&offset=${offset}`
  );
  return handleResponse(response, 'fetch history');
};

/**
 * Update relay privacy setting
 */
export const updateRelayPrivacy = async (relayId, isPublic, ownerId) => {
  const response = await safeFetch(`${API_BASE_URL}/relays/${relayId}/privacy`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ is_public: isPublic, owner_id: ownerId }),
  });
  return handleResponse(response, 'update privacy');
};

/**
 * List public relays
 */
export const listPublicRelays = async (limit = 20, offset = 0) => {
  const response = await safeFetch(`${API_BASE_URL}/relays?limit=${limit}&offset=${offset}`);
  return handleResponse(response, 'fetch relays');
};

/**
 * Create WebSocket connection for real-time updates
 */
export const connectWebSocket = (relayId, agent, onMessage, token = null) => {
  const wsUrl = API_BASE_URL.replace('https://', 'wss://').replace('http://', 'ws://');
  let url = `${wsUrl}/relays/${relayId}/ws?agent=${agent}`;
  if (token) url += `&token=${encodeURIComponent(token)}`;
  const ws = new WebSocket(url);

  ws.onopen = () => console.log(`WebSocket connected for agent: ${agent}`);
  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    onMessage(message);
  };
  ws.onerror = (error) => console.error('WebSocket error:', error);
  ws.onclose = () => console.log('WebSocket disconnected');

  return ws;
};
