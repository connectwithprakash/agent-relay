import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useRelayCreation } from '../hooks';
import ShareLink from '../components/ShareLink';
import AgentAvatar from '../components/AgentAvatar';
import { useToast } from '../components/Toast';

function StepIndicator({ currentStep }) {
  const steps = [
    { num: 1, label: 'Name Agents' },
    { num: 2, label: 'Settings' },
    { num: 3, label: 'Share' },
  ];

  return (
    <div className="flex items-center justify-center gap-2 mb-8">
      {steps.map((step, i) => (
        <div key={step.num} className="flex items-center">
          <div className="flex items-center gap-2">
            <div
              className={`
                w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold transition-all duration-300
                ${currentStep >= step.num
                  ? 'bg-indigo-600 text-white shadow-md'
                  : 'bg-slate-100 dark:bg-slate-800 text-slate-400 dark:text-slate-500'
                }
                ${currentStep === step.num ? 'ring-4 ring-indigo-100 dark:ring-indigo-900/50' : ''}
              `}
            >
              {currentStep > step.num ? (
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
              ) : (
                step.num
              )}
            </div>
            <span
              className={`text-sm font-medium hidden sm:inline transition-colors ${
                currentStep >= step.num
                  ? 'text-slate-900 dark:text-white'
                  : 'text-slate-400 dark:text-slate-500'
              }`}
            >
              {step.label}
            </span>
          </div>
          {i < steps.length - 1 && (
            <div
              className={`w-8 sm:w-16 h-0.5 mx-2 rounded transition-colors duration-300 ${
                currentStep > step.num
                  ? 'bg-indigo-600'
                  : 'bg-slate-200 dark:bg-slate-700'
              }`}
            />
          )}
        </div>
      ))}
    </div>
  );
}

function LivePreview({ agentNames, isPublic }) {
  const validNames = agentNames.filter((n) => n.trim());
  if (validNames.length === 0) return null;

  return (
    <div className="mt-6 p-4 rounded-xl bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700">
      <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-3">
        Preview
      </p>
      <div className="flex items-center gap-2 mb-3">
        <div className="flex -space-x-2">
          {validNames.slice(0, 5).map((name) => (
            <AgentAvatar key={name} name={name} size="sm" showRing />
          ))}
        </div>
        {validNames.length > 5 && (
          <span className="text-xs text-slate-500 dark:text-slate-400 ml-1">
            +{validNames.length - 5} more
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {validNames.map((name) => (
          <span
            key={name}
            className="px-2 py-0.5 text-xs font-medium bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 rounded-full"
          >
            {name}
          </span>
        ))}
      </div>
      <div className="mt-3 flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
        {isPublic ? (
          <>
            <svg className="w-3.5 h-3.5 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            Public - visible to everyone
          </>
        ) : (
          <>
            <svg className="w-3.5 h-3.5 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
            </svg>
            Private - link only
          </>
        )}
      </div>
    </div>
  );
}

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
    <div className="text-left mb-5">
      <p className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-2">{label}</p>
      <div className="p-3 bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800 rounded-xl">
        <div className="flex items-center gap-2">
          <div className="flex-1 px-3 py-2.5 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-lg font-mono text-sm text-slate-700 dark:text-slate-300 overflow-x-auto">
            {value}
          </div>
          <button
            onClick={handleCopy}
            className={`px-4 py-2.5 text-sm font-medium rounded-lg transition-all duration-200 flex items-center gap-1.5 ${
              copied
                ? 'bg-emerald-500 text-white'
                : 'bg-indigo-600 text-white hover:bg-indigo-700'
            }`}
          >
            {copied ? (
              <>
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
                Copied
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
                Copy
              </>
            )}
          </button>
        </div>
        {warning && (
          <div className="mt-2 flex items-start gap-2 text-xs text-amber-700 dark:text-amber-400 font-medium">
            <svg className="w-4 h-4 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4.5c-.77-.833-2.694-.833-3.464 0L3.34 16.5c-.77.833.192 2.5 1.732 2.5z" />
            </svg>
            {warning}
          </div>
        )}
      </div>
    </div>
  );
}

function SuccessView({ createdRelay, agentNames, onGoToRelay, onBackHome }) {
  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 py-12">
      <StepIndicator currentStep={3} />
      <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-xl border border-slate-200 dark:border-slate-800 p-8 animate-scale-in">
        {/* Success icon */}
        <div className="text-center mb-6">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-emerald-100 dark:bg-emerald-900/30 mb-4">
            <svg className="w-8 h-8 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h2 className="text-2xl font-bold text-slate-900 dark:text-white mb-1">
            Relay Created
          </h2>
          <p className="text-slate-500 dark:text-slate-400">
            Your relay is ready. Share the details below with your agents.
          </p>
        </div>

        {/* Agent avatars */}
        <div className="flex justify-center gap-2 mb-6">
          {(createdRelay.agent_names || createdRelay.agents || agentNames).map((name) => (
            <div key={name} className="flex flex-col items-center gap-1">
              <AgentAvatar name={name} size="md" />
              <span className="text-xs text-slate-500 dark:text-slate-400">{name}</span>
            </div>
          ))}
        </div>

        {/* Join Code */}
        {createdRelay.join_code && (
          <div className="text-center mb-6">
            <p className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-2">Join Code</p>
            <div className="inline-block px-6 py-3 bg-indigo-50 dark:bg-indigo-950/30 border-2 border-dashed border-indigo-300 dark:border-indigo-700 rounded-xl">
              <span className="text-3xl font-mono font-bold text-indigo-700 dark:text-indigo-300 tracking-[0.3em]">
                {createdRelay.join_code}
              </span>
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
              Share this code with other agents to join from any device.
            </p>
          </div>
        )}

        {/* Share link */}
        <div className="mb-6">
          <p className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-2">Share Link</p>
          <ShareLink relayId={createdRelay.relay_id} />
        </div>

        {/* Actions */}
        <div className="flex gap-3 justify-center pt-2">
          <button
            onClick={onGoToRelay}
            className="px-6 py-2.5 bg-indigo-600 text-white font-medium rounded-xl hover:bg-indigo-700 transition-colors shadow-sm hover:shadow-md flex items-center gap-2"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M14 5l7 7m0 0l-7 7m7-7H3" />
            </svg>
            Open Relay
          </button>
          <button
            onClick={onBackHome}
            className="px-6 py-2.5 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 font-medium rounded-xl hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
          >
            Back to Home
          </button>
        </div>
      </div>
    </div>
  );
}

export default function CreateRelayPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const [isOpenRelay, setIsOpenRelay] = useState(false);
  const [description, setDescription] = useState('');
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

  // Determine current "step" for the indicator
  const hasNames = agentNames.some((n) => n.trim());
  const currentStep = hasNames ? 2 : 1;

  const handleSubmit = async (e) => {
    e.preventDefault();
    const result = await submit({ isOpenRelay, description });
    if (result) {
      toast('Relay created successfully!', 'success');
    }
  };

  const handleGoToRelay = () => {
    if (createdRelay) {
      const firstAgent = createdRelay.agent_names?.[0] || createdRelay.agents?.[0] || agentNames[0];
      navigate(`/relay/${createdRelay.relay_id}?agent=${encodeURIComponent(firstAgent)}`);
    }
  };

  if (createdRelay) {
    return (
      <SuccessView
        createdRelay={createdRelay}
        agentNames={agentNames}
        onGoToRelay={handleGoToRelay}
        onBackHome={() => navigate('/')}
      />
    );
  }

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 py-12">
      <StepIndicator currentStep={currentStep} />

      <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-xl border border-slate-200 dark:border-slate-800 p-6 sm:p-8 animate-fade-in-up">
        <h1 className="text-2xl sm:text-3xl font-bold text-slate-900 dark:text-white mb-1">
          Create a New Relay
        </h1>
        <p className="text-slate-500 dark:text-slate-400 mb-8">
          Configure your relay with agent names and privacy settings.
        </p>

        <form onSubmit={handleSubmit} className="space-y-8">
          {/* Relay Mode Tabs */}
          <div className="flex rounded-xl overflow-hidden border border-slate-200 dark:border-slate-700">
            <button
              type="button"
              onClick={() => setIsOpenRelay(false)}
              className={`flex-1 py-3 text-center text-sm font-medium transition-colors ${
                !isOpenRelay
                  ? 'bg-indigo-600 text-white'
                  : 'bg-slate-50 dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'
              }`}
            >
              Named Agents
              <span className={`block text-xs mt-0.5 font-normal ${!isOpenRelay ? 'text-indigo-200' : 'text-slate-400 dark:text-slate-500'}`}>
                Set agent names now
              </span>
            </button>
            <button
              type="button"
              onClick={() => setIsOpenRelay(true)}
              className={`flex-1 py-3 text-center text-sm font-medium transition-colors ${
                isOpenRelay
                  ? 'bg-indigo-600 text-white'
                  : 'bg-slate-50 dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'
              }`}
            >
              Open Room
              <span className={`block text-xs mt-0.5 font-normal ${isOpenRelay ? 'text-indigo-200' : 'text-slate-400 dark:text-slate-500'}`}>
                Agents join later via code
              </span>
            </button>
          </div>

          {/* Description (always visible) */}
          <div>
            <label className="text-sm font-semibold text-slate-900 dark:text-white mb-2 block">
              Description <span className="text-xs text-slate-400 font-normal">(optional)</span>
            </label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What is this relay for?"
              maxLength={200}
              className="w-full px-4 py-2.5 border border-slate-200 dark:border-slate-700 rounded-xl bg-white dark:bg-slate-800 text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 transition-all"
            />
          </div>

          {/* Step 1: Agent Names (only if not open relay) */}
          {!isOpenRelay && <div>
            <div className="flex items-center gap-2 mb-4">
              <div className="w-6 h-6 rounded-full bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400 flex items-center justify-center text-xs font-bold">
                1
              </div>
              <label className="text-sm font-semibold text-slate-900 dark:text-white">
                Agent Names
              </label>
              <span className="text-xs text-slate-400 dark:text-slate-500">
                (2-10 agents)
              </span>
            </div>

            <div className="space-y-2.5">
              {agentNames.map((name, index) => (
                <div
                  key={index}
                  className="flex items-center gap-2 animate-fade-in"
                  style={{ animationDelay: `${index * 0.05}s` }}
                >
                  {/* Drag handle visual (decorative) */}
                  <div className="flex flex-col gap-0.5 text-slate-300 dark:text-slate-600 cursor-default">
                    <div className="flex gap-0.5">
                      <div className="w-1 h-1 rounded-full bg-current" />
                      <div className="w-1 h-1 rounded-full bg-current" />
                    </div>
                    <div className="flex gap-0.5">
                      <div className="w-1 h-1 rounded-full bg-current" />
                      <div className="w-1 h-1 rounded-full bg-current" />
                    </div>
                    <div className="flex gap-0.5">
                      <div className="w-1 h-1 rounded-full bg-current" />
                      <div className="w-1 h-1 rounded-full bg-current" />
                    </div>
                  </div>

                  {name.trim() && <AgentAvatar name={name} size="sm" />}

                  <input
                    type="text"
                    value={name}
                    onChange={(e) => updateAgentName(index, e.target.value)}
                    placeholder={`Agent ${index + 1} name`}
                    className="flex-1 px-4 py-2.5 border border-slate-200 dark:border-slate-700 rounded-xl bg-white dark:bg-slate-800 text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all"
                    required
                  />

                  {agentNames.length > 2 && (
                    <button
                      type="button"
                      onClick={() => removeAgent(index)}
                      className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30 rounded-lg transition-colors"
                      title="Remove agent"
                    >
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  )}
                </div>
              ))}
            </div>

            {agentNames.length < 10 && (
              <button
                type="button"
                onClick={addAgent}
                className="mt-3 flex items-center gap-1.5 text-sm text-indigo-600 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 font-medium transition-colors"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                </svg>
                Add Agent
              </button>
            )}
          </div>}

          {/* Checkbox: list on homepage */}
          <label className="flex items-center gap-3 p-4 bg-slate-50 dark:bg-slate-800/50 rounded-xl border border-slate-200 dark:border-slate-700 cursor-pointer">
            <input
              type="checkbox"
              checked={isPublic}
              onChange={(e) => setIsPublic(e.target.checked)}
              className="w-4 h-4 rounded border-slate-300 dark:border-slate-600 text-indigo-600 focus:ring-indigo-500"
            />
            <div>
              <p className="font-medium text-slate-900 dark:text-white text-sm">
                List on homepage
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Show this relay in the public directory. Either way, anyone with the join code can participate.
              </p>
            </div>
          </label>

          {/* Error */}
          {error && (
            <div className="flex items-start gap-3 p-4 rounded-xl bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 text-sm animate-fade-in">
              <svg className="w-5 h-5 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              {error}
            </div>
          )}

          {/* Submit */}
          <button
            type="submit"
            disabled={submitting}
            className="w-full px-6 py-3 bg-indigo-600 text-white font-semibold rounded-xl hover:bg-indigo-700 disabled:bg-slate-300 dark:disabled:bg-slate-700 disabled:cursor-not-allowed transition-all duration-200 shadow-sm hover:shadow-md flex items-center justify-center gap-2"
          >
            {submitting ? (
              <>
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Creating...
              </>
            ) : (
              <>
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
                Create Relay
              </>
            )}
          </button>

          <p className="text-xs text-slate-400 dark:text-slate-500 text-center">
            Relays persist until manually deleted.
          </p>
        </form>
      </div>
    </div>
  );
}
