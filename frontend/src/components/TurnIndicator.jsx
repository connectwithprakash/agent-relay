export default function TurnIndicator({ currentTurn, agentName }) {
  const isMyTurn = currentTurn === agentName;

  return (
    <div className="flex items-center justify-between p-4 bg-gray-50 dark:bg-gray-800 rounded-lg border-2 border-gray-200 dark:border-gray-700">
      <div className="flex items-center gap-3">
        <div
          className={`w-3 h-3 rounded-full ${
            isMyTurn
              ? 'bg-green-500 animate-pulse'
              : 'bg-gray-400'
          }`}
        />
        <span className="font-medium text-gray-900 dark:text-gray-100">
          Current Turn: <span className="font-bold">{currentTurn}</span>
        </span>
      </div>

      {isMyTurn ? (
        <span className="px-3 py-1 text-sm font-semibold text-green-700 bg-green-100 rounded-full dark:bg-green-900 dark:text-green-200">
          Your Turn
        </span>
      ) : (
        <span className="px-3 py-1 text-sm font-semibold text-gray-600 bg-gray-200 rounded-full dark:bg-gray-700 dark:text-gray-300">
          Waiting...
        </span>
      )}
    </div>
  );
}
