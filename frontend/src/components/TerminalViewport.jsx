import { useEffect, useRef } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';

export default function TerminalViewport({ output, inputEnabled, onInput }) {
  const hostRef = useRef(null);
  const terminalRef = useRef(null);
  const renderedLengthRef = useRef(0);
  const outputRef = useRef(output);
  const inputEnabledRef = useRef(inputEnabled);
  const onInputRef = useRef(onInput);
  const writeQueueRef = useRef(Promise.resolve());

  useEffect(() => { outputRef.current = output; }, [output]);
  useEffect(() => {
    inputEnabledRef.current = inputEnabled;
    if (terminalRef.current) terminalRef.current.options.cursorBlink = inputEnabled;
  }, [inputEnabled]);
  useEffect(() => { onInputRef.current = onInput; }, [onInput]);

  useEffect(() => {
    const terminal = new Terminal({
      cursorBlink: inputEnabledRef.current,
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
      fontSize: 13,
      theme: { background: '#020617', foreground: '#d1fae5', cursor: '#a7f3d0' },
    });
    const fit = new FitAddon();
    terminal.loadAddon(fit);
    terminal.open(hostRef.current);
    fit.fit();
    const queueWrite = (text) => {
      if (!text) return;
      writeQueueRef.current = writeQueueRef.current.then(() => new Promise((resolve) => {
        terminal.write(text, resolve);
      }));
    };
    queueWrite(outputRef.current);
    renderedLengthRef.current = outputRef.current.length;
    terminal.onData((data) => { if (inputEnabledRef.current) onInputRef.current(data); });
    terminalRef.current = terminal;
    const resize = new ResizeObserver(() => fit.fit());
    resize.observe(hostRef.current);
    return () => { resize.disconnect(); terminal.dispose(); };
  }, []);

  useEffect(() => {
    const terminal = terminalRef.current;
    if (!terminal) return;
    const next = output.slice(renderedLengthRef.current);
    if (next) {
      writeQueueRef.current = writeQueueRef.current.then(() => new Promise((resolve) => {
        terminal.write(next, resolve);
      }));
    }
    renderedLengthRef.current = output.length;
  }, [output]);

  return <div ref={hostRef} className="h-[48vh] min-h-72 w-full p-3" aria-label="Live managed terminal" />;
}
