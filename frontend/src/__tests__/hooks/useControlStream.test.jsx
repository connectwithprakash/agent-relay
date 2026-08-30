import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useControlStream } from '../../hooks/useControlStream';

describe('useControlStream', () => {
  it('drops replayed events at or before the durable cursor', () => {
    const sockets = [];
    class FakeWebSocket {
      static OPEN = 1;
      readyState = FakeWebSocket.OPEN;
      constructor(url, protocols) { this.url = url; this.protocols = protocols; sockets.push(this); }
      close = vi.fn();
      send = vi.fn();
    }
    vi.stubGlobal('WebSocket', FakeWebSocket);
    const onEvent = vi.fn();

    const { result, unmount } = renderHook(() => useControlStream({
      url: 'ws://relay/sessions/session-1/stream', token: 'token-value', onEvent,
    }));

    act(() => {
      sockets[0].onmessage({ data: JSON.stringify({ type: 'event', event: { sequence: 4, kind: 'output', data: { text: 'a' } } }) });
      sockets[0].onmessage({ data: JSON.stringify({ type: 'event', event: { sequence: 4, kind: 'output', data: { text: 'a' } } }) });
      sockets[0].onmessage({ data: JSON.stringify({ type: 'event', event: { sequence: 5, kind: 'output', data: { text: 'b' } } }) });
    });

    expect(onEvent).toHaveBeenCalledTimes(2);
    expect(onEvent.mock.calls.map(([frame]) => frame.event.sequence)).toEqual([4, 5]);
    expect(sockets[0].protocols).toEqual(['token-token-value']);
    act(() => result.current.reconnect());
    expect(sockets[1].url).toBe('ws://relay/sessions/session-1/stream?cursor=5');
    act(() => sockets[1].onclose({ code: 4003 }));
    expect(result.current.status).toBe('revoked');
    unmount();
  });
});
