---
name: fingerprint-rules-engine
description: Set up no-code automatic protection with the Fingerprint Rules Engine — block or allow visitors based on Smart Signals without writing decision code — and consume the rule outcome server-side. Use when the user wants automatic protection, to build their first rule, or to enforce policy without hand-coding signal checks.
---

# Fingerprint — Rules Engine (no-code protection)

Maps to the dashboard **"Build your first rule"** Get Started step. The Rules Engine lets you
block or allow requests based on Smart Signals **in the dashboard**, without writing the decision
logic yourself. It's the fastest way to get automatic protection live, and it complements (doesn't
replace) server-side verification for your most sensitive actions.

## When to use this vs. coding the checks yourself
- **Rules Engine** — broad, policy-level protection you can change without a deploy (e.g. "block
  bad bots and IP-blocklisted requests on this key"). Good default for most traffic.
- **Server-side checks** (`fingerprint-smart-signals`) — fine-grained, per-action logic tied to
  your business state (e.g. step-up auth only for first-time-device logins). Keep these for
  high-risk flows.
- Most teams use both: a ruleset for the baseline, code for the nuanced cases.

> **Rules Engine is in beta and requires Server API v4.** Docs: https://docs.fingerprint.com/docs/rules-engine.

## Set up your first rule (dashboard)
This step is configured in the dashboard, not in code:
1. In the Fingerprint Dashboard, open **Rules Engine**.
2. Click **+ New ruleset** (you'll see the initial "Identify visitors" node).
3. Click **+ Add rule**, choose a condition on the **Visitor ID or a Smart Signal** — e.g.
   `incognito is true` → response **block** (a simple, common first rule) — and set the
   condition/response in the right-hand sidebar.

> **Start from a template for a known use case.** Rather than building from scratch, point the user
> at Fingerprint's prebuilt, customizable templates — Block bots, Block VPN users, Block region
> spoofing, Account takeover (ATO) prevention, and more — at https://fingerprint.com/templates/.
> Pick the one matching their goal and tune the signals/conditions from there.
4. Click **Save** (top right). Use the ruleset's **Settings** tab to rename, describe,
   enable/disable, or delete it — and to find the **ruleset ID** you'll need in code.

## Rulesets are NOT attached to API keys
This is the key thing to get right: a ruleset is **not** bound to a public/secret API key or
environment. It is evaluated only when you **explicitly pass its `ruleset_id`** to the Server API.
Without that parameter, the event comes back with no rule outcome — which is the usual reason a
rule "doesn't seem to fire."

## Consume the outcome in code
After your normal identification, fetch the event with the `ruleset_id` query parameter on the
`GET /events/{event_id}` (v4) call — e.g. via the Server SDK `getEvent` options or directly:

```
GET https://api.fpjs.io/v4/events/<EVENT_ID>?ruleset_id=<RULESET_ID>
```

The outcome is on the event at the root-level **`rule_action`** field:
- `ruleset_id`, `rule_id` (the matched rule), and `type` (`"block"` or `"allow"`)
- for block actions, the configured `status_code`, `headers`, and `body`

Read it and honor it:
- Treat a **block** `type` as a hard stop for the action.
- Log `rule_id` so you can tune rulesets from real traffic.
- Keep your own fail-closed checks for sensitive actions — a permissive ruleset should never
  downgrade your code-level protection.

> Guard the access — `rule_action` is only present when you passed a valid `ruleset_id`.

## Verify the rule is actually working
1. Trigger a request that should match (e.g. from a flagged bot/IP, or temporarily loosen the
   condition).
2. Fetch that event via `getEvent` **with `ruleset_id` passed** — not a plain `getEvent` call,
   which won't include `rule_action`.
3. Confirm `rule_action.type` and `rule_action.rule_id` match the rule you built.

## How to apply
1. If the user just wants automatic protection, **guide them to build the ruleset in the
   dashboard** (steps above) — there's no SDK call to create rules.
2. If they want to act on rule outcomes in code, pass `ruleset_id` to `getEvent` and add a check
   on the event's `rule_action` after verification — the same place `fingerprint-smart-signals`
   runs. Remind them a plain `getEvent` (no `ruleset_id`) returns no `rule_action`.
3. Recommend starting from a use-case template (https://fingerprint.com/templates/) or one narrow
   block rule (e.g. block incognito, bad bots), verifying it, then expanding — broad rules risk
   false positives.

## Best practices
- Roll out new rules in a non-blocking/log mode first if available, then switch to block.
- For account-level logic that needs your own data (e.g. keying off a `linkedId`/`tag`), do it in
  code with `fingerprint-smart-signals` — rule conditions match on the Visitor ID and Smart
  Signals, not your custom tagging metadata.
- Don't rely on rules alone for account-level fraud — combine with server-side identity binding.
