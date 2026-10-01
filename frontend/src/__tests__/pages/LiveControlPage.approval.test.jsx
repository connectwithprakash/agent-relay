import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../components/TerminalViewport', () => ({
  default: ({ approvalPrompt, onDismissApproval, onResize }) => (
    <div aria-label="Live managed terminal">
      {approvalPrompt && <p data-testid="approval">{approvalPrompt}</p>}
      <button onClick={onDismissApproval}>mock dismiss</button>
      <button onClick={() => onResize(120, 40)}>mock resize</button>
    </div>
  ),
}));

import LiveControlPage from '../../pages/LiveControlPage';

const session = {
  session_id: 'session-1',
  profile: 'claude-code',
  worker_status: 'online',
  controller_agent: 'browser-controller',
  lease_expires_at: '2099-01-01T00:00:00+00:00',
  version: 3,
};

const frame = (kind, sequence, data) => ({ data: JSON.stringify({ type: 'event', event: { sequence, kind, data } }) });

describe('LiveControlPage approval and resize', () => {
  const sockets = [];

  beforeEach(() => {
    class FakeWebSocket {
      static OPEN = 1;
      readyState = FakeWebSocket.OPEN;
      constructor(url, protocols) { this.url = url; this.protocols = protocols; sockets.push(this); }
      close = vi.fn();
      send = vi.fn();
    }
    vi.stubGlobal('WebSocket', FakeWebSocket);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ sessions: [session] }) }));
    localStorage.setItem('relay_token_relay-1', 'browser-token');
    localStorage.setItem('relay_agent_relay-1', 'browser-controller');
  });

  afterEach(() => {
    localStorage.clear();
    sockets.length = 0;
    vi.unstubAllGlobals();
  });

  const open = async () => {
    render(
      <MemoryRouter initialEntries={['/relay/relay-1/sessions/session-1/live']}>
        <Routes><Route path="/relay/:relayId/sessions/:sessionId/live" element={<LiveControlPage />} /></Routes>
      </MemoryRouter>,
    );
    await screen.findByRole('button', { name: 'Release control' });
    act(() => sockets[0].onopen());
  };

  it('passes the approval prompt to the terminal and clears it on the next output', async () => {
    await open();
    act(() => sockets[0].onmessage(frame('approval_requested', 1, { prompt: 'Allow edit?' })));
    expect(screen.getByTestId('approval')).toHaveTextContent('Allow edit?');

    act(() => sockets[0].onmessage(frame('output', 2, { text: '1\n' })));
    expect(screen.queryByTestId('approval')).toBeNull();
  });

  it('clears the approval on dismiss', async () => {
    await open();
    act(() => sockets[0].onmessage(frame('approval_requested', 1, { prompt: 'Allow edit?' })));
    fireEvent.click(screen.getByText('mock dismiss'));
    expect(screen.queryByTestId('approval')).toBeNull();
  });

  it('replaces a pending approval with the newest prompt', async () => {
    await open();
    act(() => sockets[0].onmessage(frame('approval_requested', 1, { prompt: 'first' })));
    act(() => sockets[0].onmessage(frame('approval_requested', 2, { prompt: 'second' })));
    expect(screen.getByTestId('approval')).toHaveTextContent('second');
  });

  it('ignores an approval event without a prompt', async () => {
    await open();
    act(() => sockets[0].onmessage(frame('approval_requested', 1, {})));
    expect(screen.queryByTestId('approval')).toBeNull();
  });

  it('sends a resize frame over the stream', async () => {
    await open();
    fireEvent.click(screen.getByText('mock resize'));
    expect(sockets[0].send).toHaveBeenCalledWith(JSON.stringify({ type: 'resize', cols: 120, rows: 40 }));
  });

  it('surfaces an invalid_resize error without a message and keeps the terminal and lease', async () => {
    await open();
    act(() => sockets[0].onmessage({ data: JSON.stringify({ type: 'error', code: 'invalid_resize' }) }));
    expect(screen.getByRole('alert')).toHaveTextContent(/resize/i);
    expect(screen.getByLabelText('Live managed terminal')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Release control' })).toBeInTheDocument();
  });
});
