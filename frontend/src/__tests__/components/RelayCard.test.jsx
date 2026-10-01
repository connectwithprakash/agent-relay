import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import RelayCard from '../../components/RelayCard';

describe('RelayCard created time', () => {
  afterEach(() => vi.unstubAllEnvs());

  const renderCard = (created_at) => render(
    <MemoryRouter>
      <RelayCard relay={{ relay_id: 'relay-1', created_at, agent_names: ['a', 'b'], message_count: 0 }} />
    </MemoryRouter>,
  );

  it.each([
    ['Asia/Kolkata', 'Jan 15, 04:00 PM'],
    ['America/Los_Angeles', 'Jan 15, 02:30 AM'],
    ['UTC', 'Jan 15, 10:30 AM'],
  ])('shows an offset-less 10:30 UTC timestamp in %s as %s', (tz, expected) => {
    vi.stubEnv('TZ', tz);
    renderCard('2025-01-15T10:30:00');
    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it('shows Unknown without a timestamp', () => {
    renderCard(undefined);
    expect(screen.getByText('Unknown')).toBeInTheDocument();
  });
});
