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
        if (onOpen) onOpen();
      };

      es.addEventListener('message', (event) => {
        try {
          const data = JSON.parse(event.data);
          if (onMessage) onMessage(data);
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
        if (onError) onError(error);
      };

      eventSourceRef.current = es;
    } catch (err) {
      console.error('[SSE] Connection failed:', err);
      setConnectionStatus('error');
    }
  }, [url, enabled, onMessage, onOpen, onError, disconnect]);

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
