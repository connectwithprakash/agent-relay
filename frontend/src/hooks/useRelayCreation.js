import { useState, useCallback } from 'react';
import { createRelay } from '../utils/api';

/**
 * Custom hook for managing relay creation form state and submission
 *
 * Handles agent name inputs, privacy toggle, validation, and API submission.
 *
 * @returns {Object} Form state and control functions
 */
export function useRelayCreation() {
  const [agentNames, setAgentNames] = useState(['', '']);
  const [isPublic, setIsPublic] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [createdRelay, setCreatedRelay] = useState(null);

  const addAgent = useCallback(() => {
    setAgentNames((prev) => (prev.length < 10 ? [...prev, ''] : prev));
  }, []);

  const removeAgent = useCallback((index) => {
    setAgentNames((prev) => (prev.length > 2 ? prev.filter((_, i) => i !== index) : prev));
  }, []);

  const updateAgentName = useCallback((index, value) => {
    setAgentNames((prev) => {
      const updated = [...prev];
      updated[index] = value;
      return updated;
    });
  }, []);

  const validate = useCallback(() => {
    const trimmed = agentNames.map((n) => n.trim());
    if (trimmed.some((n) => !n)) {
      return 'All agent names are required';
    }
    const unique = new Set(trimmed);
    if (unique.size !== trimmed.length) {
      return 'Agent names must be unique';
    }
    return null;
  }, [agentNames]);

  const submit = useCallback(async () => {
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return null;
    }

    try {
      setSubmitting(true);
      setError(null);
      const trimmed = agentNames.map((n) => n.trim());
      const result = await createRelay(trimmed, null, isPublic);
      setCreatedRelay(result);
      // Store API key for this relay so dashboard can authenticate
      if (result.api_key && result.relay_id) {
        const { storeApiKey } = await import('../utils/auth.js');
        storeApiKey(result.relay_id, result.api_key);
      }
      return result;
    } catch (err) {
      setError(err.message);
      return null;
    } finally {
      setSubmitting(false);
    }
  }, [agentNames, isPublic, validate]);

  const reset = useCallback(() => {
    setAgentNames(['', '']);
    setIsPublic(false);
    setError(null);
    setCreatedRelay(null);
  }, []);

  return {
    agentNames,
    isPublic,
    submitting,
    error,
    createdRelay,
    setIsPublic,
    addAgent,
    removeAgent,
    updateAgentName,
    submit,
    reset,
  };
}
