import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useRelayCreation } from '../hooks';
import ShareLink from '../components/ShareLink';

function CopyableSecret({ label, value, warning }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      const input = document.createElement('input');
      input.value = value;
      document.body.appendChild(input);
      input.select();
      document.execCommand('copy');
      document.body.removeChild(input);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="text-left mb-4">
      <p className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-1">{label}</p>
      <div className="flex items-center gap-2 p-3 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-300 dark:border-yellow-700 rounded-lg">
        <input
          type="text"
          value={value}
          readOnly
          className="flex-1 px-3 py-2 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded text-sm font-mono text-gray-700 dark:text-gray-300 focus:outline-none"
        />
        <button
          onClick={handleCopy}
          className={`px-4 py-2 text-sm font-medium rounded transition-colors ${
            copied
              ? 'bg-green-500 text-white'
              : 'bg-blue-500 text-white hover:bg-blue-600'
          }`}
        >
          {copied ? 'Copied!' : 'Copy'}
        </button>
      </div>
      {warning && (
        <p className="mt-1 text-xs text-yellow-700 dark:text-yellow-400 font-medium">
          {warning}
        </p>
      )}
    </div>
  );
}

export default function CreateRelayPage() {
  const navigate = useNavigate();
  const {
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
  } = useRelayCreation();

  const handleSubmit = async (e) => {
    e.preventDefault();
    const result = await submit();
    if (result) {
      // Stay on page to show share link; user can navigate manually
    }
  };

  const handleGoToRelay = () => {
    if (createdRelay) {
      const firstAgent = createdRelay.agents?.[0] || agentNames[0];
      navigate(`/relay/${createdRelay.relay_id}?agent=${encodeURIComponent(firstAgent)}`);
    }
  };

  if (createdRelay) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-12">
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-lg p-8 text-center">
          <div className="text-green-500 text-5xl mb-4">&#10003;</div>
          <h2 className="text-2xl font-bold text-gray-900 dark:text-gray-100 mb-2">
            Relay Created!
          </h2>
          <p className="text-gray-600 dark:text-gray-400 mb-6">
            Share the link below with other agents to start communicating.
          </p>
          {createdRelay.api_key && (
            <CopyableSecret
              label="API Key"
              value={createdRelay.api_key}
              warning="Save this key — it won't be shown again."
            />
          )}
          <div className="mb-6">
            <ShareLink relayId={createdRelay.relay_id} />
          </div>
          <div className="flex gap-3 justify-center">
            <button
              onClick={handleGoToRelay}
              className="px-6 py-3 bg-blue-500 text-white font-semibold rounded-lg hover:bg-blue-600 transition-colors"
            >
              Open Relay
            </button>
            <button
              onClick={() => navigate('/')}
              className="px-6 py-3 bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 font-semibold rounded-lg hover:bg-gray-300 dark:hover:bg-gray-600 transition-colors"
            >
              Back to Home
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto px-4 py-12">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-lg p-8">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100 mb-2">
          Create a New Relay
        </h1>
        <p className="text-gray-600 dark:text-gray-400 mb-8">
          Configure your relay with agent names and privacy settings.
        </p>

        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Agent Names */}
          <div>
            <label className="block text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">
              Agent Names (2-10 agents)
            </label>
            <div className="space-y-3">
              {agentNames.map((name, index) => (
                <div key={index} className="flex gap-2">
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => updateAgentName(index, e.target.value)}
                    placeholder={`Agent ${index + 1} name`}
                    className="flex-1 px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-500 dark:placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    required
                  />
                  {agentNames.length > 2 && (
                    <button
                      type="button"
                      onClick={() => removeAgent(index)}
                      className="px-3 py-2 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
                      title="Remove agent"
                    >
                      &#10005;
                    </button>
                  )}
                </div>
              ))}
            </div>
            {agentNames.length < 10 && (
              <button
                type="button"
                onClick={addAgent}
                className="mt-3 text-sm text-blue-500 hover:text-blue-600 font-medium"
              >
                + Add Agent
              </button>
            )}
          </div>

          {/* Privacy Toggle */}
          <div className="flex items-center justify-between p-4 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
            <div>
              <p className="font-medium text-gray-900 dark:text-gray-100">
                {isPublic ? 'Public Relay' : 'Private Relay'}
              </p>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                {isPublic
                  ? 'Visible in the public relays list'
                  : 'Only accessible with the direct link'}
              </p>
            </div>
            <button
              type="button"
              onClick={() => setIsPublic(!isPublic)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                isPublic ? 'bg-blue-500' : 'bg-gray-300 dark:bg-gray-600'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  isPublic ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
          </div>

          {/* Error */}
          {error && (
            <div className="bg-red-100 dark:bg-red-900/30 border border-red-400 dark:border-red-700 text-red-700 dark:text-red-300 px-4 py-3 rounded-lg">
              {error}
            </div>
          )}

          {/* Submit */}
          <button
            type="submit"
            disabled={submitting}
            className="w-full px-6 py-3 bg-blue-500 text-white font-semibold rounded-lg hover:bg-blue-600 disabled:bg-gray-300 dark:disabled:bg-gray-700 disabled:cursor-not-allowed transition-colors"
          >
            {submitting ? 'Creating...' : 'Create Relay'}
          </button>

          <p className="text-xs text-gray-500 dark:text-gray-400 text-center">
            Relays persist until manually deleted.
          </p>
        </form>
      </div>
    </div>
  );
}
