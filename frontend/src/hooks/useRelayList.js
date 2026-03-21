import { useState, useEffect, useCallback } from 'react';
import { listPublicRelays } from '../utils/api';

/**
 * Custom hook for fetching and managing the public relays list
 *
 * @param {number} limit - Number of relays to fetch per page
 * @returns {Object} Relays list state and control functions
 */
export function useRelayList(limit = 20) {
  const [relays, setRelays] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchRelays = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await listPublicRelays(limit, 0);
      setRelays(Array.isArray(data) ? data : data.relays || []);
    } catch (err) {
      setError(err.message);
      console.error('Failed to fetch public relays:', err);
    } finally {
      setLoading(false);
    }
  }, [limit]);

  const refresh = useCallback(() => {
    fetchRelays();
  }, [fetchRelays]);

  useEffect(() => {
    fetchRelays();
  }, [fetchRelays]);

  return {
    relays,
    loading,
    error,
    refresh,
  };
}
