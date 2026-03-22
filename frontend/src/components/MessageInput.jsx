import { useState } from 'react';
import { useToast } from './Toast';

const MAX_CHARS = 4000;

export default function MessageInput({ onSendMessage, currentTurn, agentName, disabled }) {
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);
  const toast = useToast();

  const isMyTurn = currentTurn === agentName;
  const canSend = isMyTurn && message.trim().length > 0 && !disabled && !sending;
  const charCount = message.length;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!canSend) return;

    setSending(true);
    try {
      await onSendMessage(message.trim());
      setMessage('');
    } catch (error) {
      console.error('Failed to send message:', error);
      toast('Failed to send message: ' + error.message, 'error');
    } finally {
      setSending(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="border-t border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 p-3 sm:p-4">
      {/* Turn indicator bar */}
      {!isMyTurn && (
        <div className="flex items-center gap-2 mb-3 px-1">
          <div className="flex gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-500 typing-dot" />
            <span className="w-1.5 h-1.5 rounded-full bg-amber-500 typing-dot" />
            <span className="w-1.5 h-1.5 rounded-full bg-amber-500 typing-dot" />
          </div>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            It&apos;s <span className="font-medium text-slate-700 dark:text-slate-300">{currentTurn}&apos;s</span> turn to send a message
          </p>
        </div>
      )}

      <div className="flex gap-2 items-end">
        <div className="flex-1 relative">
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value.slice(0, MAX_CHARS))}
            onKeyPress={handleKeyPress}
            placeholder={
              isMyTurn
                ? 'Type your message... (Enter to send, Shift+Enter for new line)'
                : `Waiting for ${currentTurn} to send...`
            }
            disabled={!isMyTurn || disabled || sending}
            className="w-full p-3 pr-16 border border-slate-200 dark:border-slate-700 rounded-xl
                       bg-slate-50 dark:bg-slate-800 text-slate-900 dark:text-white
                       placeholder-slate-400 dark:placeholder-slate-500
                       focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent focus:bg-white dark:focus:bg-slate-800
                       disabled:bg-slate-100 dark:disabled:bg-slate-850 disabled:cursor-not-allowed disabled:opacity-60
                       resize-none transition-all duration-200 text-sm leading-relaxed"
            rows={2}
          />

          {/* Character count */}
          {isMyTurn && charCount > 0 && (
            <span
              className={`absolute bottom-2 right-3 text-[10px] font-medium ${
                charCount >= MAX_CHARS
                  ? 'text-red-500'
                  : charCount > MAX_CHARS * 0.9
                    ? 'text-amber-500'
                    : 'text-slate-400 dark:text-slate-500'
              }`}
            >
              {charCount >= MAX_CHARS ? `Limit reached · ${charCount}/${MAX_CHARS}` : `${charCount}/${MAX_CHARS}`}
            </span>
          )}
        </div>

        <button
          type="submit"
          disabled={!canSend}
          className="px-4 py-3 bg-indigo-600 text-white rounded-xl
                     hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500
                     disabled:bg-slate-200 dark:disabled:bg-slate-700 disabled:text-slate-400 dark:disabled:text-slate-500 disabled:cursor-not-allowed
                     transition-all duration-200 flex items-center justify-center"
          aria-label={sending ? 'Sending' : 'Send'}
        >
          {sending ? (
            <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
          ) : (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
          )}
        </button>
      </div>
    </form>
  );
}
