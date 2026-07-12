import { useState, useEffect, useCallback } from 'react';
import { getRelay } from '../utils/api';

/**
 * Custom hook for managing relay state and data fetching
 *
 * Follows Single Responsibility Principle:
 * - Only handles relay data fetching and state management
 * - Separated from UI rendering and WebSocket logic
 *
 * @param {string} relayId - The relay identifier
 * @returns {Object} Relay state and control functions
 */
export function useRelay(relayId) {
  const [relay, setRelay] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  /**
   * Fetch relay data from API
   * Uses useCallback to maintain stable reference
   */
  const fetchRelay = useCallback(async () => {
    if (!relayId) {
      setError('Relay ID is required');
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const data = await getRelay(relayId);
      setRelay(data);
    } catch (err) {
      setError(err.message);
      console.error('Failed to fetch relay:', err);
    } finally {
      setLoading(false);
    }
  }, [relayId]);

  /**
   * Update relay state locally
   * Useful for optimistic updates or WebSocket sync
   */
  const updateRelay = useCallback((updates) => {
    setRelay((prev) => (prev ? { ...prev, ...updates } : null));
  }, []);

  /**
   * Refresh relay data from server
   */
  const refresh = useCallback(() => {
    fetchRelay();
  }, [fetchRelay]);

  // Fetch relay data on mount or when dependencies change
  useEffect(() => {
    fetchRelay();
  }, [fetchRelay]);

  return {
    relay,
    loading,
    error,
    updateRelay,
    refresh,
  };
}
