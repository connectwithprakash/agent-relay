import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../components/TerminalViewport', () => ({
  default: ({ output, approvalPrompt, onDismissApproval, onResize, onInput }) => (
    <div aria-label="Live managed terminal">
      <pre data-testid="terminal-output">{output}</pre>
      {approvalPrompt && <p data-testid="approval">{approvalPrompt}</p>}
      <button onClick={onDismissApproval}>mock dismiss</button>
      <button onClick={() => onResize(120, 40)}>mock resize</button>
      <button onClick={() => onInput('1')}>mock type</button>
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

  it('passes the approval prompt to the terminal', async () => {
    await open();
    act(() => sockets[0].onmessage(frame('approval_requested', 1, { prompt: 'Allow edit?' })));
    expect(screen.getByTestId('approval')).toHaveTextContent('Allow edit?');
  });

  it('keeps the approval through spinner-style output redraws', async () => {
    await open();
    act(() => sockets[0].onmessage(frame('approval_requested', 1, { prompt: 'Allow edit?' })));
    act(() => sockets[0].onmessage(frame('output', 2, { text: '\r|' })));
    act(() => sockets[0].onmessage(frame('output', 3, { text: '\r/' })));
    expect(screen.getByTestId('approval')).toHaveTextContent('Allow edit?');
  });

  it('clears the approval when a later input_requested event arrives', async () => {
    await open();
    act(() => sockets[0].onmessage(frame('approval_requested', 1, { prompt: 'Allow edit?' })));
    act(() => sockets[0].onmessage(frame('input_requested', 2, { input: '1\n' })));
    expect(screen.queryByTestId('approval')).toBeNull();
  });

  it('does not show a stale approval when replay ends with input_requested', async () => {
    await open();
    act(() => {
      sockets[0].onmessage(frame('approval_requested', 1, { prompt: 'Allow edit?' }));
      sockets[0].onmessage(frame('output', 2, { text: 'x' }));
      sockets[0].onmessage(frame('input_requested', 3, { input: '1\n' }));
    });
    expect(screen.queryByTestId('approval')).toBeNull();
  });

  it('keeps an approval that arrives after an earlier input_requested', async () => {
    await open();
    act(() => sockets[0].onmessage(frame('input_requested', 1, { input: 'a' })));
    act(() => sockets[0].onmessage(frame('approval_requested', 2, { prompt: 'Allow edit?' })));
    expect(screen.getByTestId('approval')).toHaveTextContent('Allow edit?');
  });

  it('clears the approval when the user types into the terminal', async () => {
    await open();
    act(() => sockets[0].onmessage(frame('approval_requested', 1, { prompt: 'Allow edit?' })));
    fireEvent.click(screen.getByText('mock type'));
    expect(sockets[0].send).toHaveBeenCalledWith(JSON.stringify({ type: 'input', input: '1' }));
    expect(screen.queryByTestId('approval')).toBeNull();
  });

  it('clears the approval when the user sends the input form', async () => {
    await open();
    act(() => sockets[0].onmessage(frame('approval_requested', 1, { prompt: 'Allow edit?' })));
    fireEvent.change(screen.getByLabelText('Terminal input'), { target: { value: '1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
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
    expect(screen.getByRole('alert')).toHaveTextContent(/terminal size/i);
    expect(screen.getByLabelText('Live managed terminal')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Release control' })).toBeInTheDocument();
  });

  it.each([[42], [{ text: 'x' }], [['a']], [true], ['']])('ignores a non-string or empty approval prompt %j', async (prompt) => {
    await open();
    act(() => sockets[0].onmessage(frame('approval_requested', 1, { prompt })));
    expect(screen.queryByTestId('approval')).toBeNull();
  });

  it('never prints or echoes input_requested text', async () => {
    await open();
    act(() => sockets[0].onmessage(frame('approval_requested', 1, { prompt: 'Allow edit?' })));
    act(() => sockets[0].onmessage(frame('input_requested', 2, { input: 'secret-token\n' })));
    expect(screen.getByTestId('terminal-output')).toBeEmptyDOMElement();
    expect(document.body).not.toHaveTextContent('secret-token');
  });
});

describe('LiveControlPage session adoption', () => {
  const sockets = [];

  const respondWith = (...sessions) => {
    const queue = [...sessions];
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => ({
      ok: true,
      json: async () => ({ sessions: [queue.length > 1 ? queue.shift() : queue[0]] }),
    })));
  };

  beforeEach(() => {
    class FakeWebSocket {
      static OPEN = 1;
      readyState = FakeWebSocket.OPEN;
      constructor(url, protocols) { this.url = url; this.protocols = protocols; sockets.push(this); }
      close = vi.fn();
      send = vi.fn();
    }
    vi.stubGlobal('WebSocket', FakeWebSocket);
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
    await waitFor(() => expect(sockets).toHaveLength(1));
    act(() => sockets[0].onopen());
  };

  const detached = { ...session, status: 'detached', controller_agent: null, lease_expires_at: null, version: 4 };
  const adopted = { ...detached, status: 'ready', version: 5 };

  it('shows the session status', async () => {
    respondWith(detached);
    await open();
    expect(await screen.findByText('session detached')).toBeInTheDocument();
  });

  it('shows a detached session as ready again after session_adopted without a reload', async () => {
    respondWith(detached, adopted);
    await open();
    await screen.findByText('session detached');

    act(() => sockets[0].onmessage(frame('session_adopted', 3, {})));

    expect(await screen.findByText('session ready')).toBeInTheDocument();
    expect(screen.queryByText('session detached')).toBeNull();
    expect(sockets).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Take control' })).toBeEnabled();
  });

  it('claims the adopted session with the refreshed version', async () => {
    respondWith(detached, adopted);
    await open();
    await screen.findByText('session detached');
    act(() => sockets[0].onmessage(frame('session_adopted', 3, {})));
    await screen.findByText('session ready');
    fetch.mockClear();
    fetch.mockResolvedValue({ ok: true, json: async () => ({ ...adopted, controller_agent: 'browser-controller', lease_expires_at: '2099-01-01T00:00:00+00:00', version: 6 }) });

    fireEvent.click(screen.getByRole('button', { name: 'Take control' }));

    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toMatchObject({ expected_version: 5 });
  });

  it('does not resurrect a failed session on session_adopted', async () => {
    const failed = { ...detached, status: 'failed' };
    respondWith(failed);
    await open();
    await screen.findByText('session failed');
    fetch.mockClear();

    act(() => sockets[0].onmessage(frame('session_adopted', 3, {})));

    expect(screen.getByText('session failed')).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('keeps the server state when the refreshed session is not ready', async () => {
    respondWith(detached, { ...detached, status: 'failed' });
    await open();
    await screen.findByText('session detached');
    act(() => sockets[0].onmessage(frame('session_adopted', 3, {})));
    expect(await screen.findByText('session failed')).toBeInTheDocument();
  });
});
