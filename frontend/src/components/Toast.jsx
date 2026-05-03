import { createContext, useContext, useState, useCallback, useRef, useEffect, useMemo } from 'react';

const ToastContext = createContext(null);

let toastId = 0;

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const timers = useRef({});

  const remove = useCallback((id) => {
    clearTimeout(timers.current[id]);
    delete timers.current[id];
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  const add = useCallback((message, type) => {
    const id = ++toastId;
    setToasts(prev => [...prev, { id, message, type }]);
    timers.current[id] = setTimeout(() => remove(id), 3000);
    return id;
  }, [remove]);

  // Phase 10.1 W4: custom toast that supports an optional action button
  // and an explicit duration override. Used by BundleUpdateNotifier so the
  // "new version available" toast can surface a Refresh button and persist
  // long enough (30s) for the user to notice. Existing callers continue to
  // use toast.success/error/info unchanged.
  const addCustom = useCallback(({ message, type = 'info', action, duration = 3000 }) => {
    const id = ++toastId;
    setToasts(prev => [...prev, { id, message, type, action }]);
    timers.current[id] = setTimeout(() => remove(id), duration);
    return id;
  }, [remove]);

  useEffect(() => {
    return () => {
      Object.values(timers.current).forEach(clearTimeout);
    };
  }, []);

  const toast = useMemo(() => ({
    success: (msg) => add(msg, 'success'),
    error: (msg) => add(msg, 'error'),
    info: (msg) => add(msg, 'info'),
    custom: addCustom,
  }), [add, addCustom]);

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className="fixed top-4 right-4 z-[9999] flex flex-col gap-2 pointer-events-none">
        {toasts.map(t => (
          <div
            key={t.id}
            onClick={() => !t.action && remove(t.id)}
            className={`pointer-events-auto max-w-sm px-4 py-3 rounded-lg shadow-lg text-sm font-medium transition-all flex items-center gap-3 ${
              t.action ? '' : 'cursor-pointer'
            } ${
              t.type === 'success' ? 'bg-green-600 text-white' :
              t.type === 'error' ? 'bg-red-600 text-white' :
              'bg-blue-600 text-white'
            }`}
          >
            <span className="flex-1">{t.message}</span>
            {t.action && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  try {
                    t.action.onClick?.();
                  } finally {
                    remove(t.id);
                  }
                }}
                className="px-2 py-1 bg-white/20 hover:bg-white/30 rounded text-white text-xs font-semibold"
              >
                {t.action.label}
              </button>
            )}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}
