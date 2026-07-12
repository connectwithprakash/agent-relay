import { useEffect, useRef, useCallback, useState } from 'react';

/**
 * Fetch-based SSE hook. Native EventSource cannot send bearer headers, while
 * private relay watches require the locally persisted participant token.
 */
export function useSSE(url, options = {}) {
  const { onMessage, onOpen, onError, enabled = true, token = '' } = options;
  const controllerRef = useRef(null);
  const callbacksRef = useRef({ onMessage, onOpen, onError });
  const [connectionStatus, setConnectionStatus] = useState('disconnected');

  useEffect(() => {
    callbacksRef.current = { onMessage, onOpen, onError };
  });

  const disconnect = useCallback(() => {
    if (controllerRef.current) {
      controllerRef.current.abort();
      controllerRef.current = null;
    }
    setConnectionStatus('disconnected');
  }, []);

  const connect = useCallback(() => {
    if (!url || !enabled) return;
    disconnect();
    const controller = new AbortController();
    controllerRef.current = controller;
    setConnectionStatus('connecting');

    const run = async () => {
      while (!controller.signal.aborted) {
        try {
          const headers = token ? { Authorization: `Bearer ${token}` } : {};
          const response = await fetch(url, {
            headers,
            signal: controller.signal,
          });
          if (!response.ok || !response.body) {
            throw new Error(`SSE request failed (${response.status})`);
          }
          setConnectionStatus('connected');
          callbacksRef.current.onOpen?.();

          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = '';
          while (!controller.signal.aborted) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
            const events = buffer.split('\n\n');
            buffer = events.pop() || '';
            for (const event of events) {
              const data = event
                .split('\n')
                .filter((line) => line.startsWith('data:'))
                .map((line) => line.slice(5).trimStart())
                .join('\n');
              if (!data) continue;
              try {
                callbacksRef.current.onMessage?.(JSON.parse(data));
              } catch (error) {
                console.error('[SSE] Failed to parse message:', error);
              }
            }
          }
        } catch (error) {
          if (controller.signal.aborted) return;
          console.error('[SSE] Error:', error);
          setConnectionStatus('error');
          callbacksRef.current.onError?.(error);
        }
        if (!controller.signal.aborted) {
          await new Promise((resolve) => setTimeout(resolve, 3000));
          if (!controller.signal.aborted) setConnectionStatus('connecting');
        }
      }
    };
    run();
  }, [url, enabled, token, disconnect]);

  useEffect(() => {
    if (enabled) connect();
    return disconnect;
  }, [connect, disconnect, enabled]);

  return { connectionStatus, disconnect, reconnect: connect };
}