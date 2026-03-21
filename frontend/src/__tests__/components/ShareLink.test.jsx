import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import ShareLink from '../../components/ShareLink';

describe('ShareLink', () => {
  const relayId = 'relay-abc123';

  it('renders the share URL containing the relay ID', () => {
    render(<ShareLink relayId={relayId} />);
    const input = screen.getByRole('textbox');
    expect(input.value).toContain(`/relay/${relayId}`);
  });

  it('renders a read-only input for the URL', () => {
    render(<ShareLink relayId={relayId} />);
    const input = screen.getByRole('textbox');
    expect(input).toHaveAttribute('readOnly');
  });

  it('renders a copy button', () => {
    render(<ShareLink relayId={relayId} />);
    expect(screen.getByText('Copy')).toBeInTheDocument();
  });

  it('constructs URL from window.location.origin', () => {
    render(<ShareLink relayId={relayId} />);
    const input = screen.getByRole('textbox');
    const expectedUrl = `${window.location.origin}/relay/${relayId}`;
    expect(input.value).toBe(expectedUrl);
  });
});
