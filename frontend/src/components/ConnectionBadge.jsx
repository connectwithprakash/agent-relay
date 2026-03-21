const STATUS_CONFIG = {
  connected: {
    dot: 'bg-emerald-500',
    text: 'text-emerald-600 dark:text-emerald-400',
    label: 'Connected',
    animate: false,
    bg: 'bg-emerald-50 dark:bg-emerald-950/30',
    border: 'border-emerald-200 dark:border-emerald-800',
  },
  connecting: {
    dot: 'bg-blue-500',
    text: 'text-blue-600 dark:text-blue-400',
    label: 'Connecting',
    animate: true,
    bg: 'bg-blue-50 dark:bg-blue-950/30',
    border: 'border-blue-200 dark:border-blue-800',
  },
  reconnecting: {
    dot: 'bg-amber-500',
    text: 'text-amber-600 dark:text-amber-400',
    label: 'Reconnecting',
    animate: true,
    bg: 'bg-amber-50 dark:bg-amber-950/30',
    border: 'border-amber-200 dark:border-amber-800',
  },
  disconnected: {
    dot: 'bg-slate-400',
    text: 'text-slate-500 dark:text-slate-400',
    label: 'Offline',
    animate: false,
    bg: 'bg-slate-50 dark:bg-slate-800/30',
    border: 'border-slate-200 dark:border-slate-700',
  },
  failed: {
    dot: 'bg-red-500',
    text: 'text-red-600 dark:text-red-400',
    label: 'Failed',
    animate: false,
    bg: 'bg-red-50 dark:bg-red-950/30',
    border: 'border-red-200 dark:border-red-800',
  },
  error: {
    dot: 'bg-red-500',
    text: 'text-red-600 dark:text-red-400',
    label: 'Error',
    animate: false,
    bg: 'bg-red-50 dark:bg-red-950/30',
    border: 'border-red-200 dark:border-red-800',
  },
};

export default function ConnectionBadge({ status, compact = false }) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.disconnected;

  if (compact) {
    return (
      <span className={`inline-flex items-center gap-1.5 ${config.text} text-xs font-medium`}>
        <span className={`w-2 h-2 rounded-full ${config.dot} ${config.animate ? 'animate-pulse' : ''}`} />
        {config.label}
      </span>
    );
  }

  return (
    <span
      className={`
        inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium
        ${config.bg} ${config.border} border ${config.text}
        transition-all duration-200
      `}
    >
      <span className="relative flex h-2 w-2">
        {config.animate && (
          <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${config.dot} opacity-75`} />
        )}
        <span className={`relative inline-flex rounded-full h-2 w-2 ${config.dot}`} />
      </span>
      {config.label}
    </span>
  );
}
