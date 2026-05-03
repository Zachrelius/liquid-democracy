import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.jsx'

// Phase 10.1 W4: stale-bundle awareness. When a new service worker takes
// control of the page (meaning a new bundle is now active), dispatch a
// custom event that BundleUpdateNotifier (mounted in App.jsx) listens for
// and surfaces as a toast with a "Refresh" action. Skip the very first
// controllerchange (no prior bundle => no "update available" semantics).
if ('serviceWorker' in navigator) {
  let initialController = navigator.serviceWorker.controller;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (initialController === null) {
      initialController = navigator.serviceWorker.controller;
      return;
    }
    window.dispatchEvent(new CustomEvent('app:bundle-updated'));
  });
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
