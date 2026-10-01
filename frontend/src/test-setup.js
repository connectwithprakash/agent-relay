import '@testing-library/jest-dom'

// Node 26 exposes a global `localStorage` accessor that yields undefined unless
// --localstorage-file is set, and it shadows jsdom's implementation under vitest.
// Install an in-memory Storage when the global is not usable.
function createMemoryStorage() {
  const store = new Map()
  return {
    get length() { return store.size },
    key: (index) => Array.from(store.keys())[index] ?? null,
    getItem: (key) => (store.has(String(key)) ? store.get(String(key)) : null),
    setItem: (key, value) => { store.set(String(key), String(value)) },
    removeItem: (key) => { store.delete(String(key)) },
    clear: () => { store.clear() },
  }
}

if (typeof globalThis.localStorage?.setItem !== 'function') {
  const storage = createMemoryStorage()
  Object.defineProperty(globalThis, 'localStorage', { value: storage, configurable: true, writable: true })
  if (typeof window !== 'undefined' && window !== globalThis) {
    Object.defineProperty(window, 'localStorage', { value: storage, configurable: true, writable: true })
  }
}
