/**
 * API key storage for relay authentication.
 * Keys are stored per relay in localStorage.
 */

const STORAGE_PREFIX = 'agent_relay_key_';

export function storeApiKey(relayId, apiKey) {
  localStorage.setItem(`${STORAGE_PREFIX}${relayId}`, apiKey);
}

export function getApiKey(relayId) {
  return localStorage.getItem(`${STORAGE_PREFIX}${relayId}`);
}

export function removeApiKey(relayId) {
  localStorage.removeItem(`${STORAGE_PREFIX}${relayId}`);
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
