// v4: serve the JS Agent from your own domain, so identification runs in the same first-party
// context as the rest of your app. Only ever point this at a domain you operate.
// The single `endpoints` option replaces v3's scriptUrlPattern / endpoint / tlsEndpoint / disableTls.
// Read it from env so each environment can differ without code changes.

// --- Framework SDKs (React/Vue/Svelte/Angular) ---
// Pass `endpoints` to the provider/start options, alongside apiKey + region.
export const fingerprintLoadOptions = {
  apiKey: import.meta.env.VITE_FINGERPRINT_PUBLIC_API_KEY,
  region: import.meta.env.VITE_FINGERPRINT_REGION ?? 'us',
  // e.g. https://metrics.yourdomain.com  (string; or an array of strings for fallbacks)
  endpoints: import.meta.env.VITE_FINGERPRINT_ENDPOINTS,
}
// React:   <FingerprintProvider apiKey={...} region={...} endpoints={...}>
// Svelte:  <FingerprintProvider options={fingerprintLoadOptions}>
// Vue:     app.use(FingerprintPlugin, fingerprintLoadOptions)
// Angular: provideFingerprint({ startOptions: fingerprintLoadOptions })
// When VITE_FINGERPRINT_ENDPOINTS is unset, omit `endpoints` and the agent uses Fingerprint's
// default domain.

// --- Plain agent via CDN ---
// The script download URL is the import path (your subdomain), and `endpoints` is passed to start().
//   const fpPromise = import('https://metrics.yourdomain.com/web/v4/PUBLIC_API_KEY')
//     .then(Fingerprint => Fingerprint.start({ endpoints: 'https://metrics.yourdomain.com' }))
//   const result = await (await fpPromise).get()  // result.visitor_id, result.event_id
