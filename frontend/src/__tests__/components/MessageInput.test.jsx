import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import MessageInput from '../../components/MessageInput';

describe('MessageInput', () => {
  const defaultProps = {
    onSendMessage: vi.fn(),
    currentTurn: 'agent-1',
    agentName: 'agent-1',
    disabled: false,
  };

  it('renders the textarea and send button', () => {
    render(<MessageInput {...defaultProps} />);
    expect(screen.getByRole('textbox')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /send/i })).toBeInTheDocument();
  });

  it('disables input when it is not the agent turn', () => {
    render(<MessageInput {...defaultProps} currentTurn="agent-2" />);
    expect(screen.getByRole('textbox')).toBeDisabled();
  });

  it('shows waiting message when it is not the agent turn', () => {
    render(<MessageInput {...defaultProps} currentTurn="agent-2" />);
    // Agent name and "'s" are split across elements, so match on text content
    expect(screen.getByText((_, el) =>
      el?.tagName === 'P' &&
      el?.textContent?.includes('agent-2') &&
      el?.textContent?.includes('turn to send a message')
    )).toBeInTheDocument();
  });

  it('disables send button when message is empty', () => {
    render(<MessageInput {...defaultProps} />);
    expect(screen.getByRole('button', { name: /send/i })).toBeDisabled();
  });

  it('enables send button when it is agent turn and message is not empty', () => {
    render(<MessageInput {...defaultProps} />);
    const textarea = screen.getByRole('textbox');
    fireEvent.change(textarea, { target: { value: 'Hello' } });
    expect(screen.getByRole('button', { name: /send/i })).not.toBeDisabled();
  });

  it('calls onSendMessage with trimmed message on submit', async () => {
    const onSend = vi.fn().mockResolvedValue(undefined);
    render(<MessageInput {...defaultProps} onSendMessage={onSend} />);

    const textarea = screen.getByRole('textbox');
    fireEvent.change(textarea, { target: { value: '  Hello world  ' } });
    fireEvent.click(screen.getByRole('button', { name: /send/i }));

    await waitFor(() => {
      expect(onSend).toHaveBeenCalledWith('Hello world');
    });
  });

  it('clears textarea after successful send', async () => {
    const onSend = vi.fn().mockResolvedValue(undefined);
    render(<MessageInput {...defaultProps} onSendMessage={onSend} />);

    const textarea = screen.getByRole('textbox');
    fireEvent.change(textarea, { target: { value: 'Hello' } });
    fireEvent.click(screen.getByRole('button', { name: /send/i }));

    await waitFor(() => {
      expect(textarea.value).toBe('');
    });
  });

  it('disables input when disabled prop is true', () => {
    render(<MessageInput {...defaultProps} disabled={true} />);
    expect(screen.getByRole('textbox')).toBeDisabled();
  });
});
