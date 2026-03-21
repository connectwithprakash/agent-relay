export default function EmptyState({ icon, title, description, action }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-4 animate-fade-in">
      {icon && (
        <div className="w-16 h-16 rounded-2xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center mb-4">
          <span className="text-2xl text-slate-400 dark:text-slate-500">{icon}</span>
        </div>
      )}
      {title && (
        <h3 className="text-lg font-semibold text-slate-700 dark:text-slate-300 mb-1">
          {title}
        </h3>
      )}
      {description && (
        <p className="text-sm text-slate-500 dark:text-slate-400 text-center max-w-sm">
          {description}
        </p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
