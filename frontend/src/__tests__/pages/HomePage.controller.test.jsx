import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../hooks', () => ({
  useRelayList: () => ({ relays: [], loading: false, error: null }),
}));

import HomePage from '../../pages/HomePage';

describe('HomePage controller navigation', () => {
  afterEach(() => localStorage.clear());

  it('opens the saved controller dashboard from Home', () => {
    localStorage.setItem('relay_controller_relay-controller', 'true');
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/relay/:relayId/control" element={<p>Controller dashboard</p>} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Manage workers' }));
    expect(screen.getByText('Controller dashboard')).toBeInTheDocument();
  });
});
