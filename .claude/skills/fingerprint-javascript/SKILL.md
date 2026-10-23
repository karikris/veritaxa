---
name: fingerprint-javascript
description: Integrate Fingerprint device identification into a vanilla JavaScript or plain HTML app with the JS Agent (@fingerprint/agent, npm or CDN) — initialize the agent and get the visitor's visitor_id and event_id. Use when there's no framework SDK — Vite, Webpack, a plain script tag, Solid, Lit, Alpine, htmx, or jQuery.
---

# Fingerprint — JavaScript

Integrate Fingerprint into a vanilla JavaScript app with the JS Agent directly: initialize the
agent once at startup, then ask it for the visitor's `visitor_id` and a single-use `event_id`
wherever you need it (on load, or on an action like login or checkout).

Use this skill when there is no framework SDK to use. For React (or Preact), Vue, Angular, Svelte,
or Next.js, use `fingerprint-react` / `fingerprint-vue` / `fingerprint-angular` /
`fingerprint-svelte` / `fingerprint-nextjs` instead — they wrap this same agent with
framework-native APIs and built-in caching.

> Docs: https://docs.fingerprint.com/docs/javascript-quickstart · JS Agent v4: https://docs.fingerprint.com/reference/js-agent-v4

## Package
`@fingerprint/agent` — install the latest version. The npm package is a **loader**: it downloads
the current agent from the CDN at runtime rather than bundling the fingerprinting logic, so don't
vendor or self-host the agent bundle. With no build step, skip the install and import from the CDN
instead — see `snippets/cdn.html`.

> Fingerprint's CDN serves the agent at `/v4/<PUBLIC_API_KEY>`. A custom subdomain or proxy serves
> it one level down, at `/web/v4/<PUBLIC_API_KEY>` — `/web/` is the path prefix the proxy uses to
> separate agent downloads from identification requests on your own host, so the two URLs are
> meant to differ. See `fingerprint-proxy-integration`.

## Env var
- `FINGERPRINT_PUBLIC_API_KEY` — the public key, safe to ship to the browser.

> Bundlers only expose prefixed vars to client code — map the key to the bundler's convention:
> - Vite: `VITE_FINGERPRINT_PUBLIC_API_KEY` → `import.meta.env.VITE_...`
> - Webpack: inject with `DefinePlugin` / `EnvironmentPlugin` → `process.env.FINGERPRINT_...`
> - No bundler: there is no env-var mechanism — the key goes in the CDN import URL and ships in the
>   HTML. That's fine for a public key; restrict it with `fingerprint-request-filtering`.
> Never expose `FINGERPRINT_SECRET_API_KEY` to the frontend.

## Steps

1. **Install** `@fingerprint/agent` — or, with no build step, skip the install and import from the
   CDN (`snippets/cdn.html`) instead of adding a `package.json` the project doesn't have.

2. **Initialize once at app startup.** Call `Fingerprint.start()` with the public key and region
   (`us` | `eu` | `ap`, matching the workspace), and export the instance so the rest of the app
   reuses it. `start()` returns the agent synchronously — the agent script downloads in the
   background and `get()` waits for it. Client-side only. See `snippets/fingerprint.js`.

   Prefer `import * as Fingerprint from '@fingerprint/agent'` over a default import — the namespace
   import tree-shakes better.

3. **Get the identification where you need it.** Call `fp.get()`, which resolves to
   `{ visitor_id, event_id, ... }`. Each call is a billable identification event, so call it on the
   action you care about rather than on every page view. It accepts `{ tag, linkedId, timeout }`.
   See `snippets/identify.js`.

4. **Verify it works.** Disable your ad blocker, run the dev server, trigger the call, and confirm
   a `visitor_id` is logged in the browser console (or that the event appears on the dashboard
   Events page).

## Notes
- Region must match the workspace (`us` | `eu` | `ap`).
- Call `start()` once for the whole app; don't re-start per page or per action. In a SPA, keep the
  agent at module level so it survives client-side route changes — the deprecated
  `fingerprintjs-pro-spa` wrapper is not needed.
- Don't block the UI on identification. `get()` rejects when the agent is blocked, offline, or
  times out — catch it, use `isFingerprintError(error)` and `error.code` to log the cause, and let
  the flow continue.
- Caching is **off** by default. If you enable the `cache` option, a cache hit returns the *same*
  `event_id` (with `cache_hit: true`), which fails server-side freshness and one-time-use checks —
  keep `get()` uncached for security-relevant actions.
- Don't run the agent in a sandboxed iframe; it isn't supported.
- **Production:** serve the agent from your own domain (first-party custom subdomain or proxy) so
  identification stays consistent under browser third-party storage limits — see
  `fingerprint-proxy-integration`.
- Don't use legacy `@fingerprintjs/fingerprintjs-pro`, `FingerprintJS.load()`, or `scriptUrlPattern`.
  The result fields are `visitor_id` and `event_id`; `visitorId` and `requestId` are v3 names and do
  not exist in v4.
