import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import TurnIndicator from '../../components/TurnIndicator';

describe('TurnIndicator', () => {
  const agents = ['alice', 'bob'];

  it('shows "Your Turn" badge when currentTurn matches agentName', () => {
    render(
      <TurnIndicator currentTurn="alice" agentName="alice" agents={agents} />
    );
    expect(screen.getByText('Your Turn')).toBeInTheDocument();
  });

  it('shows "Waiting..." badge when currentTurn does not match agentName', () => {
    render(
      <TurnIndicator currentTurn="bob" agentName="alice" agents={agents} />
    );
    expect(screen.getByText('Waiting...')).toBeInTheDocument();
  });

  it('displays all agent names when agents list is provided', () => {
    render(
      <TurnIndicator currentTurn="alice" agentName="alice" agents={agents} />
    );
    expect(screen.getByText('alice')).toBeInTheDocument();
    expect(screen.getByText('bob')).toBeInTheDocument();
  });

  it('shows "(you)" label next to the current agent', () => {
    render(
      <TurnIndicator currentTurn="alice" agentName="alice" agents={agents} />
    );
    expect(screen.getByText('(you)')).toBeInTheDocument();
  });

  it('renders fallback display when agents list is empty', () => {
    render(
      <TurnIndicator currentTurn="alice" agentName="alice" agents={[]} />
    );
    expect(screen.getByText('Current Turn:')).toBeInTheDocument();
    expect(screen.getByText('alice')).toBeInTheDocument();
  });

  it('highlights the active agent pill', () => {
    const { container } = render(
      <TurnIndicator currentTurn="alice" agentName="bob" agents={agents} />
    );
    // The active agent pill should have the indigo ring styling
    const pills = container.querySelectorAll('.rounded-full');
    const activePill = Array.from(pills).find(el =>
      el.className.includes('ring-2')
    );
    expect(activePill).toBeTruthy();
    expect(activePill.textContent).toContain('alice');
  });
});
