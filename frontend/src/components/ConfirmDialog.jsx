import { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react';

const ConfirmContext = createContext(null);

export function ConfirmProvider({ children }) {
  // Phase 85 — optional `checkbox: { label, description }`. When present the
  // dialog renders a checkbox and resolves with an object
  // `{ confirmed, checked }`; without it the dialog resolves a plain boolean
  // (unchanged for every existing caller).
  const [state, setState] = useState(null);
  const [checked, setChecked] = useState(false);
  const confirmBtnRef = useRef(null);
  const cancelBtnRef = useRef(null);

  const confirm = useCallback(({ title, message, destructive = false, checkbox = null } = {}) => {
    return new Promise((resolve) => {
      setChecked(false);
      setState({ title, message, destructive, checkbox, resolve });
    });
  }, []);

  function handleConfirm() {
    if (state?.checkbox) {
      state.resolve({ confirmed: true, checked });
    } else {
      state?.resolve(true);
    }
    setState(null);
  }

  function handleCancel() {
    if (state?.checkbox) {
      state.resolve({ confirmed: false, checked: false });
    } else {
      state?.resolve(false);
    }
    setState(null);
  }

  // Focus the confirm button when dialog opens; handle Esc and Enter
  useEffect(() => {
    if (!state) return;
    cancelBtnRef.current?.focus();

    function onKeyDown(e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        handleCancel();
      } else if (e.key === 'Enter') {
        e.preventDefault();
        handleConfirm();
      } else if (e.key === 'Tab') {
        // Simple focus trap between cancel and confirm
        const btns = [cancelBtnRef.current, confirmBtnRef.current].filter(Boolean);
        if (btns.length < 2) return;
        const idx = btns.indexOf(document.activeElement);
        if (idx === -1) {
          e.preventDefault();
          btns[0].focus();
        } else if (e.shiftKey && idx === 0) {
          e.preventDefault();
          btns[btns.length - 1].focus();
        } else if (!e.shiftKey && idx === btns.length - 1) {
          e.preventDefault();
          btns[0].focus();
        }
      }
    }

    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [state]);

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {state && (
        <div className="fixed inset-0 z-[10000] flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40" onClick={handleCancel} />
          <div className="relative bg-white rounded-xl shadow-xl max-w-md w-full mx-4 p-6 space-y-4">
            {state.title && (
              <h3 className="text-lg font-semibold text-gray-800">{state.title}</h3>
            )}
            <p className="text-sm text-gray-600">{state.message}</p>
            {state.checkbox && (
              <label className="flex items-start gap-2 text-sm text-gray-700 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(e) => setChecked(e.target.checked)}
                  className="mt-0.5"
                />
                <span>
                  <span className="font-medium">{state.checkbox.label}</span>
                  {state.checkbox.description && (
                    <span className="block text-xs text-gray-500">
                      {state.checkbox.description}
                    </span>
                  )}
                </span>
              </label>
            )}
            <div className="flex justify-end gap-3 pt-2">
              <button
                ref={cancelBtnRef}
                onClick={handleCancel}
                className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
              <button
                ref={confirmBtnRef}
                onClick={handleConfirm}
                className={`text-sm px-4 py-2 rounded-lg text-white transition-colors ${
                  state.destructive
                    ? 'bg-red-600 hover:bg-red-700'
                    : 'bg-[var(--brand-primary)] hover:bg-[var(--brand-accent)]'
                }`}
              >
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  );
}

export function useConfirm() {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error('useConfirm must be used within ConfirmProvider');
  return ctx;
}
