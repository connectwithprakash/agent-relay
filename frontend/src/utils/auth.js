/**
 * Token storage for relay authentication.
 * Tokens are stored per relay in localStorage.
 */

const STORAGE_PREFIX = 'relay_token_';

export function storeToken(relayId, token) {
  localStorage.setItem(`${STORAGE_PREFIX}${relayId}`, token);
}

export function getToken(relayId) {
  return localStorage.getItem(`${STORAGE_PREFIX}${relayId}`);
}

export function removeToken(relayId) {
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