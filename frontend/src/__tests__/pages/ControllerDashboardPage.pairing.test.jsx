import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ControllerDashboardPage from '../../pages/ControllerDashboardPage';

describe('ControllerDashboardPage pairing', () => {
  beforeEach(() => {
    localStorage.setItem('relay_token_relay-1', 'controller-token');
  });

  afterEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it('creates short-lived browser and work-computer invitations from the dashboard', async () => {
    const fetchMock = vi.fn((url) => {
      if (url.includes('/workers')) return Promise.resolve({ ok: true, json: async () => ({ workers: [] }) });
      if (url.includes('/sessions')) return Promise.resolve({ ok: true, json: async () => ({ sessions: [] }) });
      if (url.includes('/unpaired-participants')) return Promise.resolve({ ok: true, json: async () => ({ participants: ['work-mac'] }) });
      if (url.includes('/controller-browser-invitations')) return Promise.resolve({ ok: true, json: async () => ({ invitation: 'browser-code' }) });
      if (url.includes('/invitations')) return Promise.resolve({ ok: true, json: async () => ({ invitation: 'worker-code' }) });
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(
      <MemoryRouter initialEntries={['/relay/relay-1/control']}>
        <Routes><Route path="/relay/:relayId/control" element={<ControllerDashboardPage />} /></Routes>
      </MemoryRouter>,
    );

    await screen.findByRole('button', { name: 'Create browser code' });
    fireEvent.click(screen.getByRole('button', { name: 'Create browser code' }));
    await screen.findByText('browser-code');

    fireEvent.click(screen.getByRole('button', { name: 'Create work-computer code' }));
    await screen.findByText('worker-code');
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('agent_name=work-mac'), expect.any(Object)));
  });
});
