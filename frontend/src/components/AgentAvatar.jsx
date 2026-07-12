const AGENT_COLORS = [
  { bg: 'bg-indigo-500', text: 'text-white', ring: 'ring-indigo-200 dark:ring-indigo-800' },
  { bg: 'bg-emerald-500', text: 'text-white', ring: 'ring-emerald-200 dark:ring-emerald-800' },
  { bg: 'bg-amber-500', text: 'text-white', ring: 'ring-amber-200 dark:ring-amber-800' },
  { bg: 'bg-rose-500', text: 'text-white', ring: 'ring-rose-200 dark:ring-rose-800' },
  { bg: 'bg-cyan-500', text: 'text-white', ring: 'ring-cyan-200 dark:ring-cyan-800' },
  { bg: 'bg-violet-500', text: 'text-white', ring: 'ring-violet-200 dark:ring-violet-800' },
  { bg: 'bg-orange-500', text: 'text-white', ring: 'ring-orange-200 dark:ring-orange-800' },
  { bg: 'bg-teal-500', text: 'text-white', ring: 'ring-teal-200 dark:ring-teal-800' },
  { bg: 'bg-pink-500', text: 'text-white', ring: 'ring-pink-200 dark:ring-pink-800' },
  { bg: 'bg-sky-500', text: 'text-white', ring: 'ring-sky-200 dark:ring-sky-800' },
];

/**
 * Generate a consistent color index from a string.
 */
function hashString(str) {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash);
    hash = hash & hash;
  }
  return Math.abs(hash);
}

// eslint-disable-next-line react-refresh/only-export-components
export function getAgentColor(name) {
  const index = hashString(name) % AGENT_COLORS.length;
  return AGENT_COLORS[index];
}

// eslint-disable-next-line react-refresh/only-export-components
export function getAgentBubbleColor(name) {
  const BUBBLE_COLORS = [
    { bg: 'bg-indigo-500', text: 'text-white' },
    { bg: 'bg-emerald-500', text: 'text-white' },
    { bg: 'bg-amber-500', text: 'text-white' },
    { bg: 'bg-rose-500', text: 'text-white' },
    { bg: 'bg-cyan-600', text: 'text-white' },
    { bg: 'bg-violet-500', text: 'text-white' },
    { bg: 'bg-orange-500', text: 'text-white' },
    { bg: 'bg-teal-500', text: 'text-white' },
    { bg: 'bg-pink-500', text: 'text-white' },
    { bg: 'bg-sky-500', text: 'text-white' },
  ];
  const index = hashString(name) % BUBBLE_COLORS.length;
  return BUBBLE_COLORS[index];
}

const SIZE_CLASSES = {
  xs: 'w-6 h-6 text-[10px]',
  sm: 'w-8 h-8 text-xs',
  md: 'w-10 h-10 text-sm',
  lg: 'w-12 h-12 text-base',
  xl: 'w-16 h-16 text-lg',
};

export default function AgentAvatar({ name, size = 'md', showRing = false, active = false }) {
  const color = getAgentColor(name || '?');
  const initial = (name || '?')[0].toUpperCase();
  const sizeClass = SIZE_CLASSES[size] || SIZE_CLASSES.md;

  return (
    <div
      className={`
        ${sizeClass} ${color.bg} ${color.text}
        rounded-full flex items-center justify-center font-semibold
        flex-shrink-0 select-none
        ${showRing ? `ring-2 ${color.ring}` : ''}
        ${active ? 'ring-2 ring-green-400 ring-offset-2 ring-offset-white dark:ring-offset-slate-900' : ''}
        transition-all duration-200
      `}
      title={name}
    >
      {initial}
    </div>
  );
}
