---
name: fingerprint-get-started
description: Guide the user through the full Fingerprint Get Started flow — detect the project's tech stack, install frontend identification, add the server-side API verification step, then walk the remaining protection steps, applying the matching skill for each. Use when the user wants to add Fingerprint to an app, get started with Fingerprint, or set up device identification and fraud protection end to end.
---

# Fingerprint — Get Started

Walk the user through the complete Fingerprint **Get Started** flow (the same checklist as the
dashboard), from first install to production-grade protection. Detect what's already done, then
apply or guide the matching skill for each remaining step. Do the steps in order; don't skip ahead
unless the user asks.

This skill is an **orchestrator** — its job is to detect the stack and delegate to the per-stack
and feature skills below. The actual SDK setup lives in those skills. In Claude Code, invoke a
skill with the Skill tool; in other agents, load and follow the named skill.

## How to run
1. **Audit the project first.** Grep for existing Fingerprint usage so you don't redo finished
   work: look for `@fingerprint/`, `fingerprint-server-sdk`, `FingerprintProvider`,
   `useVisitorData`, `getEvent`, `FINGERPRINT_*` env var names, `tag` / `linkedId`. Build a quick
   status of which steps below are done.
2. **Report the checklist** with each step marked done / not done.
3. **Walk the not-done steps in order.** For each, explain what it does, then apply the matching
   skill and follow it. Steps that are dashboard-only (rules, request filtering,
   team invites) can't be done from code — give the user the exact dashboard actions and offer to
   make any companion code change.
4. **After each step, tell the user how to verify it** (the dashboard Get Started page checks the
   same conditions — e.g. a received event, a Server API call, a tagged event).

## Detect the stack (before steps 1–2)
Read the project's manifests (don't guess from directory names):
- **Node**: `package.json` `dependencies` + `devDependencies`.
- **Python**: `requirements.txt`, `pyproject.toml`.
- **No manifest at all**: an `index.html` is a static site — still a supported frontend, with no
  build step and no env vars (the public key goes in the agent's CDN import URL).
- Check up to ~2 levels deep for monorepos (`apps/`, `packages/`, `pnpm-workspace.yaml`); a repo
  can have a separate frontend and backend.

Map detected frameworks to skills:

| Detected | Skill | Role |
| --- | --- | --- |
| `next` | `fingerprint-nextjs` | fullstack (covers both halves) |
| `react`, `react-native` | `fingerprint-react` | frontend |
| `vue`, `nuxt` | `fingerprint-vue` | frontend |
| `@angular/core` | `fingerprint-angular` | frontend |
| `svelte` (incl. SvelteKit) | `fingerprint-svelte` | frontend |
| `solid-js`, `lit`, `alpinejs`, `htmx.org`, `jquery` | `fingerprint-javascript` | frontend |
| `express`, `fastify`, `koa`, `@nestjs/core`, `@hapi/hapi` | `fingerprint-node` | backend |
| `fastapi`, `django`, `flask` | `fingerprint-python` | backend |
| *(no dependency matched above)* an `index.html` entry — plain HTML/JS, or a Vite/Webpack vanilla template | `fingerprint-javascript` | frontend |

- If you detect **Next.js**, `fingerprint-nextjs` covers both the install and server steps.
- Otherwise pick **one frontend** skill for step 1 and **one backend** skill for step 2.
- Match on dependencies first. The last row is a fallback: only use it once you've confirmed none
  of the packages above are present. When several match (jQuery inside a React app), the framework
  SDK wins — it wraps the same agent with framework-native APIs.
- A frontend with no framework SDK still has a curated skill — use `fingerprint-javascript` rather
  than the docs fallback.
- If nothing matches a curated skill, fall back to the docs (start at
  `https://docs.fingerprint.com/llms.txt`).

## The checklist

### Quick start
1. **Install Fingerprint (frontend)** — add visitor identification to the client and capture the
   first event.
   → Apply the matching frontend skill: `fingerprint-react` / `fingerprint-vue` /
   `fingerprint-angular` / `fingerprint-svelte` / `fingerprint-javascript` (no framework SDK), or
   `fingerprint-nextjs` (which also covers step 2).
   *Done when the client calls `getData()` and an event is received.*
2. **Access detailed insights (backend / Server API)** — verify the event server-side and read
   Smart Signals.
   → Apply the matching backend skill: `fingerprint-node` / `fingerprint-python` for the
   verification flow, then `fingerprint-smart-signals` to act on the full signal set.
   *Done when the server calls `getEvent` and reads signals.*

   > **Strongly recommended for security-sensitive actions** (login, signup, checkout): the client
   > only identifies — a real trust decision needs the server to verify the event. This is the
   > recommended next step, not a hard requirement (Next.js does both in one skill).

3. **Serve the agent from your own domain** (listed in the dashboard as *Protect against ad
   blockers*) — a first-party custom subdomain or proxy integration, so identification stays
   accurate and consistent under browser third-party storage limits.
   → Apply `fingerprint-proxy-integration`. A `pending` subdomain leaves this step waiting, not
   done. *Done when the agent loads and sends requests through your own domain.*

### Beyond the basics
4. **Build your first rule** — no-code automatic protection via the Rules Engine.
   → Apply `fingerprint-rules-engine` (dashboard setup + optional code to honor outcomes).
5. **Tag an event with your data** — attach user/account/order IDs to events.
   → Apply `fingerprint-tagging`. *Done when a tagged event is received.*
6. **Protect your public API key** — request filtering / allowed origins.
   → Apply `fingerprint-request-filtering` (dashboard setup; enumerate the app's real origins).
7. **Invite your team members** — dashboard-only. Point the user to the dashboard team settings;
   there's nothing to change in code. Pricing isn't seat-based, so they can invite freely.
8. **Upgrade to Pro Plus** — dashboard-only. New accounts trial **Fingerprint Pro Plus**; once the
   trial ends, the account is downgraded to the **Free** plan. If they want to keep Pro Plus
   features, point them to the dashboard billing/plan settings to upgrade before the trial ends.

## How to verify the install (after steps 1–2)
- **Preview the app**, trigger the action you wired up (e.g. load the page, submit a login/signup),
  and check that a new event appears on the **Events page in the Fingerprint dashboard**
  (https://dashboard.fingerprint.com). An event with an `event_id` confirms identification works
  end to end.
- If no event shows up, the usual cause is an **ad blocker** eating the request during testing —
  disable it and retry. For production accuracy, do step 3.

## Rules
- Step 1 is complete once identification works (an event is received). The later steps are
  recommendations, not mandatory gates — for security-sensitive actions, strongly recommend step 2
  (server-side verification), but don't block step 1 on it.
- Never read/print `.env`; reference env vars by name. Never put the secret key in client code.
- Match the existing code style; make minimal, focused edits. Tell the user which packages to
  install rather than pinning versions yourself.
- Region must match the workspace region (`us` | `eu` | `ap`) on every side.
- If the user only wants one step, jump straight to that step's skill.
