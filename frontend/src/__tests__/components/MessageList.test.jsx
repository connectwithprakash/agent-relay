import { render, screen } from '@testing-library/react';
import { afterEach, describe, it, expect, beforeAll, vi } from 'vitest';
import MessageList from '../../components/MessageList';

// jsdom does not implement scrollIntoView
beforeAll(() => {
  Element.prototype.scrollIntoView = () => {};
});

describe('MessageList', () => {
  const mockMessages = [
    {
      id: 'msg-1',
      agent: 'agent-1',
      content: 'Hello from agent 1',
      created_at: '2025-01-15T10:30:00Z',
    },
    {
      id: 'msg-2',
      agent: 'agent-2',
      content: 'Hello from agent 2',
      created_at: '2025-01-15T10:31:00Z',
    },
  ];

  it('renders empty state when no messages', () => {
    render(<MessageList messages={[]} currentAgent="agent-1" />);
    expect(screen.getByText(/no messages yet/i)).toBeInTheDocument();
  });

  it('renders all messages', () => {
    render(<MessageList messages={mockMessages} currentAgent="agent-1" />);
    expect(screen.getByText('Hello from agent 1')).toBeInTheDocument();
    expect(screen.getByText('Hello from agent 2')).toBeInTheDocument();
  });

  it('displays agent names on messages', () => {
    render(<MessageList messages={mockMessages} currentAgent="agent-1" />);
    expect(screen.getByText('agent-1')).toBeInTheDocument();
    expect(screen.getByText('agent-2')).toBeInTheDocument();
  });

  it('displays formatted timestamps', () => {
    render(<MessageList messages={mockMessages} currentAgent="agent-1" />);
    // Timestamps should be formatted as time strings
    const timeElements = screen.getAllByText(/\d{1,2}:\d{2}/);
    expect(timeElements.length).toBeGreaterThan(0);
  });

  it('renders messages with correct alignment for current agent', () => {
    const { container } = render(
      <MessageList messages={mockMessages} currentAgent="agent-1" />
    );
    // Select only the top-level message row containers (direct children of the scrollable list)
    const messageRows = container.querySelectorAll('.space-y-4 > div.animate-fade-in');
    const rightAligned = Array.from(messageRows).filter(el => el.classList.contains('justify-end'));
    // Only agent-1 messages should be right-aligned
    expect(rightAligned.length).toBe(1);
  });

  describe('offset-less server timestamps', () => {
    afterEach(() => vi.unstubAllEnvs());

    it.each([
      ['Asia/Kolkata', '04:00 PM'],
      ['America/Los_Angeles', '02:30 AM'],
      ['UTC', '10:30 AM'],
    ])('shows 10:30 UTC in %s as %s', (tz, expected) => {
      vi.stubEnv('TZ', tz);
      const messages = [{ id: 'm', agent: 'agent-1', content: 'hi', created_at: '2025-01-15T10:30:00' }];
      render(<MessageList messages={messages} currentAgent="agent-1" />);
      expect(screen.getByText(expected)).toBeInTheDocument();
    });
  });
});
