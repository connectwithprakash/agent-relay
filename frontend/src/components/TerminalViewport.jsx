import { useCallback, useEffect, useRef } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';

const RESIZE_DEBOUNCE_MS = 150;
const COLS_RANGE = [20, 500];
const ROWS_RANGE = [5, 200];

const inRange = (value, [min, max]) => Number.isInteger(value) && value >= min && value <= max;

export default function TerminalViewport({ output, inputEnabled, onInput, onResize, approvalPrompt, onDismissApproval }) {
  const hostRef = useRef(null);
  const terminalRef = useRef(null);
  const renderedLengthRef = useRef(0);
  const outputRef = useRef(output);
  const inputEnabledRef = useRef(inputEnabled);
  const onInputRef = useRef(onInput);
  const writeQueueRef = useRef(Promise.resolve());
  const onResizeRef = useRef(onResize);
  const resizeTimerRef = useRef(null);

  useEffect(() => { outputRef.current = output; }, [output]);
  useEffect(() => {
    inputEnabledRef.current = inputEnabled;
    if (terminalRef.current) terminalRef.current.options.cursorBlink = inputEnabled;
  }, [inputEnabled]);
  useEffect(() => { onInputRef.current = onInput; }, [onInput]);
  useEffect(() => { onResizeRef.current = onResize; }, [onResize]);

  const scheduleResizeReport = useCallback((cols, rows) => {
    clearTimeout(resizeTimerRef.current);
    if (!inputEnabledRef.current || !inRange(cols, COLS_RANGE) || !inRange(rows, ROWS_RANGE)) return;
    resizeTimerRef.current = setTimeout(() => onResizeRef.current?.(cols, rows), RESIZE_DEBOUNCE_MS);
  }, []);

  useEffect(() => {
    if (inputEnabled && terminalRef.current) scheduleResizeReport(terminalRef.current.cols, terminalRef.current.rows);
  }, [inputEnabled, scheduleResizeReport]);

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
    terminal.onResize(({ cols, rows }) => scheduleResizeReport(cols, rows));
    terminalRef.current = terminal;
    const resize = new ResizeObserver(() => fit.fit());
    resize.observe(hostRef.current);
    return () => { clearTimeout(resizeTimerRef.current); resize.disconnect(); terminal.dispose(); };
  }, [scheduleResizeReport]);

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

  return (
    <>
      {typeof approvalPrompt === 'string' && approvalPrompt && (
        <div role="alert" className="flex max-h-40 items-start justify-between gap-3 overflow-auto border-b border-amber-700 bg-amber-950 px-4 py-3 text-sm text-amber-100">
          <div className="min-w-0">
            <p className="font-semibold">Approval requested</p>
            <p className="mt-1 whitespace-pre-wrap break-words font-mono text-xs">{approvalPrompt}</p>
            <p className="mt-1 text-xs text-amber-300">Answer in the terminal below.</p>
          </div>
          <button type="button" onClick={onDismissApproval} className="shrink-0 rounded-lg border border-amber-600 px-3 py-1 text-xs font-semibold">Dismiss</button>
        </div>
      )}
      <div ref={hostRef} className="h-[48vh] min-h-72 w-full p-3" aria-label="Live managed terminal" />
    </>
  );
}
