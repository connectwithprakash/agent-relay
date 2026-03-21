import { render, screen, act, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import WaitingRoom from '../../components/WaitingRoom';

// Mock the api module
vi.mock('../../utils/api', () => ({
  getRelay: vi.fn(),
}));

import { getRelay } from '../../utils/api';

describe('WaitingRoom', () => {
  const baseRelay = {
    id: 'relay-abc123456789',
    status: 'open',
    agent_names: ['alice'],
    min_agents: 3,
    join_code: 'XYZ789',
    description: 'A test relay for discussion',
  };

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    getRelay.mockResolvedValue(baseRelay);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('renders the waiting room heading', () => {
    render(<WaitingRoom relay={baseRelay} relayId="relay-abc123456789" />);
    expect(screen.getByText('Waiting Room')).toBeInTheDocument();
  });

  it('displays the relay description', () => {
    render(<WaitingRoom relay={baseRelay} relayId="relay-abc123456789" />);
    expect(screen.getAllByText('A test relay for discussion').length).toBeGreaterThanOrEqual(1);
  });

  it('displays the join code prominently', () => {
    render(<WaitingRoom relay={baseRelay} relayId="relay-abc123456789" />);
    expect(screen.getAllByText('XYZ789').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Share this join code').length).toBeGreaterThanOrEqual(1);
  });

  it('shows waiting message', () => {
    render(<WaitingRoom relay={baseRelay} relayId="relay-abc123456789" />);
    expect(screen.getAllByText('Waiting for agents to join...').length).toBeGreaterThanOrEqual(1);
  });

  it('displays agents who have joined', () => {
    render(<WaitingRoom relay={baseRelay} relayId="relay-abc123456789" />);
    expect(screen.getAllByText('alice').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Joined').length).toBeGreaterThanOrEqual(1);
  });

  it('shows progress as "X of Y agents needed"', () => {
    render(<WaitingRoom relay={baseRelay} relayId="relay-abc123456789" />);
    expect(screen.getAllByText(/1/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/of/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/3/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/agents needed/).length).toBeGreaterThanOrEqual(1);
  });

  it('renders a progress bar with correct aria attributes', () => {
    render(<WaitingRoom relay={baseRelay} relayId="relay-abc123456789" />);
    const progressBars = screen.getAllByRole('progressbar');
    expect(progressBars.length).toBeGreaterThanOrEqual(1);
    expect(progressBars[0]).toHaveAttribute('aria-valuenow', '1');
    expect(progressBars[0]).toHaveAttribute('aria-valuemax', '3');
  });

  it('shows "No agents have joined yet" when agent list is empty', () => {
    const emptyRelay = { ...baseRelay, agent_names: [] };
    render(<WaitingRoom relay={emptyRelay} relayId="relay-abc123456789" />);
    expect(screen.getAllByText('No agents have joined yet').length).toBeGreaterThanOrEqual(1);
  });

  it('shows truncated relay ID', () => {
    render(<WaitingRoom relay={baseRelay} relayId="relay-abc123456789" />);
    expect(screen.getAllByText(/Relay relay-abc123/).length).toBeGreaterThanOrEqual(1);
  });

  it('polls relay state every 3 seconds', async () => {
    render(<WaitingRoom relay={baseRelay} relayId="relay-abc123456789" />);

    await act(async () => {
      vi.advanceTimersByTime(3000);
    });

    expect(getRelay).toHaveBeenCalledWith('relay-abc123456789');
  });

  it('calls onActivate when relay status becomes active', async () => {
    const onActivate = vi.fn();
    const activatedRelay = {
      ...baseRelay,
      status: 'active',
      agent_names: ['alice', 'bob', 'charlie'],
    };
    getRelay.mockResolvedValue(activatedRelay);

    render(
      <WaitingRoom relay={baseRelay} relayId="relay-abc123456789" onActivate={onActivate} />
    );

    await act(async () => {
      vi.advanceTimersByTime(3000);
    });

    await waitFor(() => {
      expect(onActivate).toHaveBeenCalledWith(activatedRelay);
    });
  });

  it('calls onActivate when min_agents threshold is met', async () => {
    const onActivate = vi.fn();
    const updatedRelay = {
      ...baseRelay,
      agent_names: ['alice', 'bob', 'charlie'],
    };
    getRelay.mockResolvedValue(updatedRelay);

    render(
      <WaitingRoom relay={baseRelay} relayId="relay-abc123456789" onActivate={onActivate} />
    );

    await act(async () => {
      vi.advanceTimersByTime(3000);
    });

    await waitFor(() => {
      expect(onActivate).toHaveBeenCalledWith(updatedRelay);
    });
  });

  it('hides join code section when no join code is available', () => {
    const noCodeRelay = { ...baseRelay, join_code: '' };
    render(<WaitingRoom relay={noCodeRelay} relayId="relay-abc123456789" />);
    expect(screen.queryByText('Share this join code')).not.toBeInTheDocument();
  });

  it('hides description when not set', () => {
    const noDescRelay = { ...baseRelay, description: '' };
    render(<WaitingRoom relay={noDescRelay} relayId="relay-abc123456789" />);
    expect(screen.queryByText('A test relay for discussion')).not.toBeInTheDocument();
  });

  it('copies join code to clipboard on button click', async () => {
    const mockClipboard = { writeText: vi.fn().mockResolvedValue(undefined) };
    Object.assign(navigator, { clipboard: mockClipboard });

    render(<WaitingRoom relay={baseRelay} relayId="relay-abc123456789" />);

    const copyButtons = screen.getAllByTitle('Copy join code');
    await act(async () => {
      fireEvent.click(copyButtons[0]);
    });

    expect(mockClipboard.writeText).toHaveBeenCalledWith('XYZ789');
  });
});
