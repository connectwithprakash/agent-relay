import { useState } from 'react';
import { updateRelayPrivacy } from '../utils/api';

export default function PrivacyToggle({ relayId, isPublic: initialIsPublic, ownerId, onUpdate }) {
  const [isPublic, setIsPublic] = useState(initialIsPublic);
  const [updating, setUpdating] = useState(false);

  const handleToggle = async () => {
    try {
      setUpdating(true);
      const newIsPublic = !isPublic;
      await updateRelayPrivacy(relayId, newIsPublic, ownerId);
      setIsPublic(newIsPublic);
      if (onUpdate) onUpdate(newIsPublic);
    } catch (error) {
      console.error('Failed to update privacy:', error);
      alert('Failed to update privacy: ' + error.message);
    } finally {
      setUpdating(false);
    }
  };

  return (
    <div className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
      <div className="flex items-center gap-2">
        {isPublic ? (
          <svg className="w-5 h-5 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        ) : (
          <svg className="w-5 h-5 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
          </svg>
        )}
        <div>
          <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
            {isPublic ? 'Public Relay' : 'Private Relay'}
          </p>
          <p className="text-xs text-gray-600 dark:text-gray-400">
            {isPublic
              ? 'Anyone can view this relay'
              : 'Only you can view this relay'}
          </p>
        </div>
      </div>

      <button
        onClick={handleToggle}
        disabled={updating}
        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
          isPublic
            ? 'bg-green-500'
            : 'bg-gray-300 dark:bg-gray-600'
        } ${updating ? 'opacity-50 cursor-not-allowed' : ''}`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
            isPublic ? 'translate-x-6' : 'translate-x-1'
          }`}
        />
      </button>
    </div>
  );
}
