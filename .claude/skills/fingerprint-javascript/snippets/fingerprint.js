// src/fingerprint.js — start the agent once at app startup, export the instance.
// `start()` returns the agent synchronously; the agent script itself downloads in the
// background, and `get()` waits for it. The region MUST match your workspace
// ('us' | 'eu' | 'ap') or identification fails with "API key not found".
import * as Fingerprint from '@fingerprint/agent'

export const fp = Fingerprint.start({
  apiKey: import.meta.env.VITE_FINGERPRINT_PUBLIC_API_KEY,
  region: import.meta.env.VITE_FINGERPRINT_REGION,
})
