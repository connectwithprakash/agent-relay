import { useEffect, useRef, useCallback, useState } from 'react';

/**
 * Custom hook for WebSocket connection with automatic reconnection
 *
 * Uses refs for callback props to prevent reconnection loops when
 * callers pass inline arrow functions (which change identity every render).
 *
 * @param {string} url - WebSocket URL
 * @param {Object} options - Configuration options
 * @param {Function} options.onMessage - Message handler
 * @param {Function} options.onOpen - Connection opened handler
 * @param {Function} options.onClose - Connection closed handler
 * @param {Function} options.onError - Error handler
 * @param {boolean} options.enabled - Whether to connect (default: true)
 * @param {number} options.reconnectInterval - Base reconnect interval in ms (default: 3000)
 * @param {number} options.maxReconnectAttempts - Max reconnection attempts (default: 5)
 * @returns {Object} WebSocket state and control functions
 */
export function useWebSocket(url, options = {}) {
  const {
    onMessage,
    onOpen,
    onClose,
    onError,
    enabled = true,
    reconnectInterval = 3000,
    maxReconnectAttempts = 5,
  } = options;

  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const reconnectAttemptsRef = useRef(0);
  const shouldReconnectRef = useRef(false);
  const [connectionStatus, setConnectionStatus] = useState('disconnected');

  // Store callbacks in refs to avoid triggering reconnects when
  // inline arrow functions change identity between renders
  const callbacksRef = useRef({ onMessage, onOpen, onClose, onError });
  useEffect(() => {
    callbacksRef.current = { onMessage, onOpen, onClose, onError };
  });

  /**
   * Clear reconnection timeout
   */
  const clearReconnectTimeout = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
  }, []);

  /**
   * Connect to WebSocket
   */
  const connect = useCallback(() => {
    if (!url || !enabled) return;

    try {
      setConnectionStatus('connecting');
      const ws = new WebSocket(url);

      ws.onopen = () => {
        if (wsRef.current !== ws) return;
        console.log('[WebSocket] Connected');
        setConnectionStatus('connected');
        reconnectAttemptsRef.current = 0; // Reset attempts on successful connection
        if (callbacksRef.current.onOpen) callbacksRef.current.onOpen();
      };

      ws.onmessage = (event) => {
        if (wsRef.current !== ws) return;
        try {
          const message = JSON.parse(event.data);
          if (callbacksRef.current.onMessage) callbacksRef.current.onMessage(message);
        } catch (err) {
          console.error('[WebSocket] Failed to parse message:', err);
        }
      };

      ws.onerror = (error) => {
        if (wsRef.current !== ws) return;
        console.error('[WebSocket] Error:', error);
        setConnectionStatus('error');
        if (callbacksRef.current.onError) callbacksRef.current.onError(error);
      };

      ws.onclose = (event) => {
        // Ignore close events from sockets intentionally replaced by a newer one.
        if (wsRef.current !== ws) return;
        console.log('[WebSocket] Disconnected:', event.reason);
        setConnectionStatus('disconnected');
        wsRef.current = null;

        if (callbacksRef.current.onClose) callbacksRef.current.onClose(event);

        // Attempt reconnection with exponential backoff
        if (shouldReconnectRef.current && reconnectAttemptsRef.current < maxReconnectAttempts) {
          const backoffTime =
            reconnectInterval * Math.pow(2, reconnectAttemptsRef.current);
          reconnectAttemptsRef.current += 1;

          console.log(
            `[WebSocket] Reconnecting in ${backoffTime}ms (attempt ${reconnectAttemptsRef.current}/${maxReconnectAttempts})`
          );

          setConnectionStatus('reconnecting');
          reconnectTimeoutRef.current = setTimeout(() => {
            // eslint-disable-next-line react-hooks/immutability
            connect();
          }, backoffTime);
        } else if (reconnectAttemptsRef.current >= maxReconnectAttempts) {
          console.error('[WebSocket] Max reconnection attempts reached');
          setConnectionStatus('failed');
        }
      };

      wsRef.current = ws;
    } catch (err) {
      console.error('[WebSocket] Connection failed:', err);
      setConnectionStatus('error');
    }
  }, [url, enabled, reconnectInterval, maxReconnectAttempts]);

  /**
   * Disconnect WebSocket
   */
  const disconnect = useCallback(() => {
    shouldReconnectRef.current = false;
    clearReconnectTimeout();
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setConnectionStatus('disconnected');
  }, [clearReconnectTimeout]);

  /**
   * Send message through WebSocket
   */
  const send = useCallback((data) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(typeof data === 'string' ? data : JSON.stringify(data));
      return true;
    }
    console.warn('[WebSocket] Cannot send: connection not open');
    return false;
  }, []);

  /**
   * Manually trigger reconnection
   */
  const reconnect = useCallback(() => {
    disconnect();
    reconnectAttemptsRef.current = 0;
    shouldReconnectRef.current = true;
    connect();
  }, [disconnect, connect]);

  // Connect on mount or when URL/enabled changes
  useEffect(() => {
    if (enabled && url) {
      shouldReconnectRef.current = true;
      connect();
    }

    return () => {
      shouldReconnectRef.current = false;
      clearReconnectTimeout();
      disconnect();
    };
  }, [connect, disconnect, enabled, url, clearReconnectTimeout]);

  return {
    connectionStatus,
    send,
    reconnect,
    disconnect,
  };
}
