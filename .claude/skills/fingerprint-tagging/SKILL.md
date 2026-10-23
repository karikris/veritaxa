---
name: fingerprint-tagging
description: Attach your own metadata (user IDs, account IDs, order IDs) to Fingerprint identification events using tag and linkedId in the v4 JS Agent, then read it back from the Server API and webhooks. Use to join Fingerprint data with your business data for fraud use-cases, tracking logged-in devices, and analytics.
---

# Fingerprint — Tagging events with your data (v4)

Maps to the dashboard **"Tag an event with your data"** Get Started step. Tagging attaches your
own context (user/account/order IDs, a plan name, a flow name) to an identification event so you
can join Fingerprint's `visitor_id` and signals with your business data — in the Server API, in
webhooks, and in dashboard search.

> **Note the client→server name change:** you send **`tag`** in the client `getData(...)` call, but
> it comes back on the server event as **`event.tags`** (plural). `linkedId` → `event.linked_id`.

## Two tools
- **`tag`** — arbitrary JSON metadata stored on the event (e.g. `{ userId, orderId, action }`).
  Use it to label *what the user was doing* when identified.
- **`linkedId`** — a string that groups related events under one identifier (e.g. a session id or
  a user id). Use it to **follow one entity across many events** and to query them together.

## Where it goes
Pass both when you identify, on the client. With the v4 React/Vue/Svelte/Angular SDKs the
identify call accepts them:

```js
// React/Next.js — useVisitorData hook
const { getData } = useVisitorData({ immediate: false })
const { event_id } = await getData({
  tag: { action: 'checkout', orderId, plan: 'pro' },
  linkedId: `user_${userId}`,
})
```

See `snippets/identify-with-tag.jsx` (client) and `snippets/read-tag.js` (server).

## How to apply
1. **Tag at the moment of the action**, alongside the existing identify call — don't add a second
   identify just to tag. The action handler already calls `getData()`; pass `tag`/`linkedId` there.
2. **Put identifiers in `linkedId`, descriptive context in `tag`.** `linkedId` is what you'll
   filter/group by; `tag` is the payload you read back.
3. **Send the `event_id` to your backend as usual.** The tag and linkedId come back on the
   server-side event from `getEvent(eventId)` (`event.tags`, `event.linked_id`) — verify the event
   first, then trust the tag you yourself set.
4. **Never put secrets or sensitive PII in a tag** — tags are set from the browser and are visible
   in the dashboard. Use opaque ids (`user_123`), not emails or tokens.
5. **Keep tags small and consistent** — a stable shape (`{ action, userId, ... }`) makes dashboard
   search and downstream joins reliable.

## Verify it worked
After wiring it up, trigger the tagged action once and confirm the tag appears: search recent
events in the dashboard (or via `search_events`) and check `event.tags` / `event.linked_id`. This
is exactly what the Get Started step checks for.

## Framework notes
- **React / Next.js**: `getData({ tag, linkedId })` from `useVisitorData`.
- **Vue / Svelte**: same `getData({ tag, linkedId })` on the composable/hook result.
- **Angular**: `fingerprint.getVisitorData({ tag, linkedId })`.
- **Plain JS Agent / CDN**: `fp.get({ tag, linkedId })`.
