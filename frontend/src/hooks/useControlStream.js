import { useCallback, useEffect, useRef, useState } from 'react';

export function useControlStream({ url, token, onEvent }) {
  const socketRef = useRef(null);
  const cursorRef = useRef(0);
  const onEventRef = useRef(onEvent);
  const [status, setStatus] = useState('disconnected');

  useEffect(() => {
    onEventRef.current = onEvent;
  });

  const connect = useCallback(() => {
    if (!url || !token) return;
    setStatus('connecting');
    const socket = new WebSocket(`${url}?cursor=${cursorRef.current}`, [`token-${token}`]);
    socketRef.current = socket;
    socket.onopen = () => setStatus('connected');
    socket.onmessage = ({ data }) => {
      const frame = JSON.parse(data);
      if (frame.type === 'event' && frame.event?.sequence) {
        if (frame.event.sequence <= cursorRef.current) return;
        cursorRef.current = frame.event.sequence;
      }
      onEventRef.current?.(frame);
    };
    socket.onerror = () => setStatus('error');
    socket.onclose = (event) => setStatus(event.code === 4003 ? 'revoked' : 'disconnected');
  }, [token, url]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    connect();
    return () => socketRef.current?.close();
  }, [connect]);

  const sendInput = useCallback((input) => {
    if (socketRef.current?.readyState !== WebSocket.OPEN) return false;
    socketRef.current.send(JSON.stringify({ type: 'input', input }));
    return true;
  }, []);

  return { status, sendInput, reconnect: connect };
}
