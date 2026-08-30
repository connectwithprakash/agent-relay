/**
 * Credential storage for relay authentication.
 * Tokens and their bound participant identities are stored per relay.
 */

const STORAGE_PREFIX = 'relay_token_';
const AGENT_PREFIX = 'relay_agent_';
const CONTROLLER_PREFIX = 'relay_controller_';

export function storeToken(relayId, token, agent = null, canControl = false) {
  localStorage.setItem(`${STORAGE_PREFIX}${relayId}`, token);
  if (agent) localStorage.setItem(`${AGENT_PREFIX}${relayId}`, agent);
  if (canControl) localStorage.setItem(`${CONTROLLER_PREFIX}${relayId}`, 'true');
}

export function getToken(relayId) {
  return localStorage.getItem(`${STORAGE_PREFIX}${relayId}`);
}

export function getAgent(relayId) {
  return localStorage.getItem(`${AGENT_PREFIX}${relayId}`);
}

export function removeToken(relayId) {
  localStorage.removeItem(`${STORAGE_PREFIX}${relayId}`);
  localStorage.removeItem(`${AGENT_PREFIX}${relayId}`);
  localStorage.removeItem(`${CONTROLLER_PREFIX}${relayId}`);
}

export function getAllStoredRelays() {
  const relays = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key.startsWith(STORAGE_PREFIX)) {
      relays.push(key.substring(STORAGE_PREFIX.length));
    }
  }
  return relays;
}

export function getControllerRelays() {
  const relays = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key.startsWith(CONTROLLER_PREFIX) && localStorage.getItem(key) === 'true') {
      relays.push(key.substring(CONTROLLER_PREFIX.length));
    }
  }
  return relays;
}
