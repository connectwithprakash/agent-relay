import { useState } from 'react';

export default function MessageInput({ onSendMessage, currentTurn, agentName, disabled }) {
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);

  const isMyTurn = currentTurn === agentName;
  const canSend = isMyTurn && message.trim().length > 0 && !disabled && !sending;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!canSend) return;

    setSending(true);
    try {
      await onSendMessage(message.trim());
      setMessage('');
    } catch (error) {
      console.error('Failed to send message:', error);
      alert('Failed to send message: ' + error.message);
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
    <form onSubmit={handleSubmit} className="p-4 border-t border-gray-200 dark:border-gray-700">
      <div className="flex gap-2">
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyPress={handleKeyPress}
          placeholder={
            isMyTurn
              ? 'Type your message... (Enter to send, Shift+Enter for new line)'
              : `Waiting for ${currentTurn} to send...`
          }
          disabled={!isMyTurn || disabled || sending}
          className="flex-1 p-3 border border-gray-300 dark:border-gray-600 rounded-lg
                     bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100
                     placeholder-gray-500 dark:placeholder-gray-400
                     focus:outline-none focus:ring-2 focus:ring-blue-500
                     disabled:bg-gray-100 dark:disabled:bg-gray-900 disabled:cursor-not-allowed
                     resize-none"
          rows={3}
        />
        <button
          type="submit"
          disabled={!canSend}
          className="px-6 py-3 bg-blue-500 text-white font-semibold rounded-lg
                     hover:bg-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-500
                     disabled:bg-gray-300 dark:disabled:bg-gray-700 disabled:cursor-not-allowed
                     transition-colors"
        >
          {sending ? 'Sending...' : 'Send'}
        </button>
      </div>
      {!isMyTurn && (
        <p className="text-sm text-gray-600 dark:text-gray-400 mt-2">
          It's {currentTurn}'s turn to send a message
        </p>
      )}
    </form>
  );
}
