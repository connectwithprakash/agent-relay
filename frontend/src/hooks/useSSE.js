import { useEffect, useRef, useCallback, useState } from 'react';

/**
 * Custom hook for Server-Sent Events (SSE) connection
 *
 * Used for spectator/watch mode to receive real-time relay messages
 * without participating in the turn system.
 *
 * @param {string} url - SSE endpoint URL
 * @param {Object} options - Configuration options
 * @param {Function} options.onMessage - Message handler
 * @param {Function} options.onOpen - Connection opened handler
 * @param {Function} options.onError - Error handler
 * @param {boolean} options.enabled - Whether to connect (default: true)
 * @returns {Object} SSE state and control functions
 */
export function useSSE(url, options = {}) {
  const { onMessage, onOpen, onError, enabled = true } = options;

  const eventSourceRef = useRef(null);
  const [connectionStatus, setConnectionStatus] = useState('disconnected');

  // Store callbacks in refs to avoid reconnect loops from inline arrow functions
  const callbacksRef = useRef({ onMessage, onOpen, onError });
  useEffect(() => {
    callbacksRef.current = { onMessage, onOpen, onError };
  });

  const disconnect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    setConnectionStatus('disconnected');
  }, []);

  const connect = useCallback(() => {
    if (!url || !enabled) return;

    disconnect();
    setConnectionStatus('connecting');

    try {
      const es = new EventSource(url);

      es.onopen = () => {
        setConnectionStatus('connected');
        if (callbacksRef.current.onOpen) callbacksRef.current.onOpen();
      };

      es.addEventListener('message', (event) => {
        try {
          const data = JSON.parse(event.data);
          if (callbacksRef.current.onMessage) callbacksRef.current.onMessage(data);
        } catch (err) {
          console.error('[SSE] Failed to parse message:', err);
        }
      });

      es.onerror = (error) => {
        console.error('[SSE] Error:', error);
        if (es.readyState === EventSource.CLOSED) {
          setConnectionStatus('disconnected');
        } else {
          setConnectionStatus('error');
        }
        if (callbacksRef.current.onError) callbacksRef.current.onError(error);
      };

      eventSourceRef.current = es;
    } catch (err) {
      console.error('[SSE] Connection failed:', err);
      setConnectionStatus('error');
    }
  }, [url, enabled, disconnect]);

  useEffect(() => {
    if (enabled) {
      connect();
    }
    return () => {
      disconnect();
    };
  }, [connect, disconnect, enabled]);

  return {
    connectionStatus,
    disconnect,
    reconnect: connect,
  };
}
