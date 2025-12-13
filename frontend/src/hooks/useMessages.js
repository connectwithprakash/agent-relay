import { useState, useEffect, useCallback } from 'react';
import { getHistory, sendMessage } from '../utils/api';

/**
 * Custom hook for managing relay messages
 *
 * Follows Single Responsibility Principle:
 * - Only handles message state and operations
 * - Separated from relay state and WebSocket logic
 *
 * @param {string} relayId - The relay identifier
 * @param {string} agentName - Current agent name
 * @returns {Object} Messages state and operations
 */
export function useMessages(relayId, agentName) {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [sending, setSending] = useState(false);

  /**
   * Fetch message history from API
   */
  const fetchMessages = useCallback(async () => {
    if (!relayId) {
      setError('Relay ID is required');
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const data = await getHistory(relayId);
      setMessages(data.messages || []);
    } catch (err) {
      setError(err.message);
      console.error('Failed to fetch messages:', err);
    } finally {
      setLoading(false);
    }
  }, [relayId]);

  /**
   * Add a new message to the list
   * Used for WebSocket real-time updates
   */
  const addMessage = useCallback((message) => {
    setMessages((prev) => [...prev, message]);
  }, []);

  /**
   * Send a message to the relay
   */
  const send = useCallback(
    async (content) => {
      if (!relayId || !agentName) {
        throw new Error('Relay ID and agent name are required');
      }

      try {
        setSending(true);
        const response = await sendMessage(relayId, content, agentName);

        // Note: Don't add message here - it will come through WebSocket
        // This prevents duplicate messages

        return response;
      } catch (err) {
        console.error('Failed to send message:', err);
        throw err;
      } finally {
        setSending(false);
      }
    },
    [relayId, agentName]
  );

  /**
   * Clear all messages
   */
  const clearMessages = useCallback(() => {
    setMessages([]);
  }, []);

  /**
   * Refresh messages from server
   */
  const refresh = useCallback(() => {
    fetchMessages();
  }, [fetchMessages]);

  // Fetch messages on mount or when relay ID changes
  useEffect(() => {
    fetchMessages();
  }, [fetchMessages]);

  return {
    messages,
    loading,
    error,
    sending,
    addMessage,
    send,
    clearMessages,
    refresh,
  };
}
