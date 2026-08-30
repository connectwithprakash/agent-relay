import { render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const terminals = [];

vi.mock('@xterm/xterm', () => ({
  Terminal: class {
    constructor(options) {
      this.options = options;
      this.write = vi.fn((text, callback) => { this.pendingWrite = callback; });
      this.loadAddon = vi.fn();
      this.open = vi.fn();
      this.onData = vi.fn();
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
});
