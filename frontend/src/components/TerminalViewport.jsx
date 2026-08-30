import { useEffect, useRef } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';

export default function TerminalViewport({ output, inputEnabled, onInput }) {
  const hostRef = useRef(null);
  const terminalRef = useRef(null);
  const renderedLengthRef = useRef(0);
  const outputRef = useRef(output);

  useEffect(() => { outputRef.current = output; }, [output]);

  useEffect(() => {
    const terminal = new Terminal({
      cursorBlink: inputEnabled,
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
      fontSize: 13,
      theme: { background: '#020617', foreground: '#d1fae5', cursor: '#a7f3d0' },
    });
    const fit = new FitAddon();
    terminal.loadAddon(fit);
    terminal.open(hostRef.current);
    fit.fit();
    terminal.write(outputRef.current);
    renderedLengthRef.current = outputRef.current.length;
    terminal.onData((data) => { if (inputEnabled) onInput(data); });
    terminalRef.current = terminal;
    const resize = new ResizeObserver(() => fit.fit());
    resize.observe(hostRef.current);
    return () => { resize.disconnect(); terminal.dispose(); };
  }, [inputEnabled, onInput]);

  useEffect(() => {
    const terminal = terminalRef.current;
    if (!terminal) return;
    terminal.write(output.slice(renderedLengthRef.current));
    renderedLengthRef.current = output.length;
  }, [output]);

  return <div ref={hostRef} className="h-[48vh] min-h-72 w-full p-3" aria-label="Live managed terminal" />;
}
