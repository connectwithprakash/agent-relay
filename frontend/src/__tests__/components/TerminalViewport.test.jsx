import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const terminals = [];

vi.mock('@xterm/xterm', () => ({
  Terminal: class {
    constructor(options) {
      this.options = options;
      this.write = vi.fn((text, callback) => { this.pendingWrite = callback; });
      this.loadAddon = vi.fn();
      this.open = vi.fn();
      this.onData = vi.fn();
      this.onResize = vi.fn((handler) => { this.resizeHandler = handler; });
      this.cols = 80;
      this.rows = 24;
      this.dispose = vi.fn();
      terminals.push(this);
    }
  },
}));

vi.mock('@xterm/addon-fit', () => ({
  FitAddon: class {
    fit = vi.fn();
  },
}));

import TerminalViewport from '../../components/TerminalViewport';

describe('TerminalViewport', () => {
  afterEach(() => {
    terminals.length = 0;
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('queues output chunks until xterm finishes the preceding write', async () => {
    vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
    const { rerender } = render(<TerminalViewport output="first" inputEnabled={false} onInput={vi.fn()} />);
    const terminal = terminals[0];

    await vi.waitFor(() => expect(terminal.write).toHaveBeenCalledWith('first', expect.any(Function)));
    rerender(<TerminalViewport output="firstsecond" inputEnabled onInput={vi.fn()} />);

    expect(terminals).toHaveLength(1);
    expect(terminal.write).toHaveBeenCalledTimes(1);
    terminal.pendingWrite();
    await vi.waitFor(() => expect(terminal.write).toHaveBeenLastCalledWith('second', expect.any(Function)));
  });

  describe('resize', () => {
    const setup = (props = {}) => {
      vi.useFakeTimers();
      vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
      const onResize = vi.fn();
      const view = render(<TerminalViewport output="" inputEnabled onInput={vi.fn()} onResize={onResize} {...props} />);
      return { onResize, terminal: terminals[0], ...view };
    };
    const emit = (terminal, cols, rows) => act(() => { terminal.resizeHandler({ cols, rows }); });

    it('reports the new size once after a burst of resizes', () => {
      const { onResize, terminal } = setup();
      onResize.mockClear();
      emit(terminal, 100, 30);
      emit(terminal, 110, 32);
      act(() => { vi.advanceTimersByTime(300); });
      expect(onResize).toHaveBeenCalledTimes(1);
      expect(onResize).toHaveBeenCalledWith(110, 32);
    });

    it.each([[19, 24], [501, 24], [80, 4], [80, 201], [80.5, 24], [true, 24], [80, true], ['80', '24']])('ignores out of bounds size %s x %s', (cols, rows) => {
      const { onResize, terminal } = setup();
      onResize.mockClear();
      emit(terminal, cols, rows);
      act(() => { vi.advanceTimersByTime(300); });
      expect(onResize).not.toHaveBeenCalled();
    });

    it('accepts the bound values', () => {
      const { onResize, terminal } = setup();
      onResize.mockClear();
      emit(terminal, 20, 5);
      act(() => { vi.advanceTimersByTime(300); });
      emit(terminal, 500, 200);
      act(() => { vi.advanceTimersByTime(300); });
      expect(onResize.mock.calls).toEqual([[20, 5], [500, 200]]);
    });

    it('does not report while input is disabled', () => {
      const { onResize, terminal } = setup({ inputEnabled: false });
      emit(terminal, 100, 30);
      act(() => { vi.advanceTimersByTime(300); });
      expect(onResize).not.toHaveBeenCalled();
    });

    it('reports the current size once the stream becomes usable', () => {
      const { onResize, terminal, rerender } = setup({ inputEnabled: false });
      terminal.cols = 90;
      terminal.rows = 28;
      rerender(<TerminalViewport output="" inputEnabled onInput={vi.fn()} onResize={onResize} />);
      act(() => { vi.advanceTimersByTime(300); });
      expect(onResize).toHaveBeenCalledWith(90, 28);
    });

    it('drops a pending report on unmount', () => {
      const { onResize, terminal, unmount } = setup();
      onResize.mockClear();
      emit(terminal, 100, 30);
      unmount();
      act(() => { vi.advanceTimersByTime(300); });
      expect(onResize).not.toHaveBeenCalled();
    });
  });

  describe('approval banner', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} }));

    it('shows nothing without a pending approval', () => {
      render(<TerminalViewport output="" inputEnabled onInput={vi.fn()} />);
      expect(screen.queryByRole('alert')).toBeNull();
    });

    it('shows the prompt text as plain text', () => {
      render(<TerminalViewport output="" inputEnabled onInput={vi.fn()} approvalPrompt="Allow <b>rm -rf</b>?" />);
      expect(screen.getByRole('alert')).toHaveTextContent('Allow <b>rm -rf</b>?');
    });

    it('caps the banner height so a long prompt cannot push the terminal away', () => {
      render(<TerminalViewport output="" inputEnabled onInput={vi.fn()} approvalPrompt={'x'.repeat(4096)} />);
      expect(screen.getByRole('alert')).toHaveClass('max-h-40', 'overflow-auto');
    });

    it('calls onDismissApproval when dismissed', () => {
      const onDismissApproval = vi.fn();
      render(<TerminalViewport output="" inputEnabled onInput={vi.fn()} approvalPrompt="Proceed?" onDismissApproval={onDismissApproval} />);
      fireEvent.click(screen.getByRole('button', { name: /dismiss/i }));
      expect(onDismissApproval).toHaveBeenCalledTimes(1);
    });
  });
});
