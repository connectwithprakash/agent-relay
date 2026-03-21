import { Link } from 'react-router-dom';

export default function NotFoundPage() {
  return (
    <div className="flex items-center justify-center min-h-[60vh] px-4">
      <div className="max-w-md w-full text-center">
        <h1 className="text-6xl font-bold text-slate-300 dark:text-slate-700 mb-4">
          404
        </h1>
        <h2 className="text-xl font-semibold text-slate-900 dark:text-white mb-2">
          Page not found
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400 mb-6">
          The page you are looking for does not exist or has been moved.
        </p>
        <Link
          to="/"
          className="inline-flex items-center gap-2 px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg transition-colors"
        >
          Go Home
        </Link>
      </div>
    </div>
  );
}
