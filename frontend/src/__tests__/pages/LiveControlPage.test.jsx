import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import LiveControlPage from '../../pages/LiveControlPage';

describe('LiveControlPage', () => {
  it('does not expose a live control surface without a stored relay credential', () => {
    render(
      <MemoryRouter initialEntries={['/relay/relay-1/sessions/session-1/live']}>
        <Routes><Route path="/relay/:relayId/sessions/:sessionId/live" element={<LiveControlPage />} /></Routes>
      </MemoryRouter>
    );

    expect(screen.getByText('Relay access required')).toBeInTheDocument();
    expect(screen.queryByLabelText('Terminal input')).not.toBeInTheDocument();
  });
});
