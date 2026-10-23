---
name: fingerprint-request-filtering
description: Configure Fingerprint request filtering in the dashboard — allowed origins, header restrictions and block lists so your public API key only works from your own apps, plus the Exclude AI Bots and Exclude Search Bots toggles that drop crawler traffic before it's billed. Use when securing the public key, preventing key abuse, setting up allow/block lists, or cutting billable crawler traffic.
---

# Fingerprint — Protect your public API key (request filtering)

Maps to the dashboard **"Protect your public API key"** Get Started step. The public API key ships
in your client source, so anyone can read it. Request filtering rules make the key only usable
from **your** apps, so a copied key can't rack up usage or pollute your data elsewhere.

This is configured in the dashboard against the environment's public key — there is no code change
beyond keeping the agent's origin consistent.

Two separate things live under **Security**, and it's worth knowing which one you want:
**Web** restricts *who* may use the key (origins, headers), below. **Bots** drops crawler traffic
before it's billed — a different problem, covered under *Filter crawler traffic*.

> Docs: AI bot filtering (https://docs.fingerprint.com/docs/ai-bot-filtering) · search bot filtering
> (https://docs.fingerprint.com/docs/search-bots-filtering)

## Set up request filtering (dashboard)
1. In the dashboard, go to **Security → Web**.
2. Under **Websites**, click **Configure** and set an **allowlist** of the exact origins your app
   loads the agent from (e.g. `https://app.yourdomain.com`, plus `http://localhost:3000` for local
   dev). Requests from other origins are rejected. (Use a blocklist instead to deny specific origins.)
3. Optionally, under **Forbidden HTTP Headers**, click **Add rule** to restrict by header.
4. Save and test: a request from an allowed origin succeeds; one from an unlisted origin is blocked.
   Rule changes can take up to ~5 minutes to take effect.

## Filter crawler traffic (dashboard: Security → Bots)
Two toggles, both off by default. They exist to stop crawlers burning billable API calls:

| Toggle | Covers |
| --- | --- |
| **Exclude AI Bots** | ~14 AI user agents — `GPTBot`, `ChatGPT-User`, `OAI-SearchBot`, `ClaudeBot`, `GoogleOther`, `Applebot`, `Amazonbot`, `PetalBot`, `DuckAssistbot`, `meta-externalagent`, and similar |
| **Exclude Search Bots** | ~24 search/aggregator sources — Googlebot and its variants, `bingbot`, `AdIdxBot`, Yandex, Baidu, Sogou, Naver, Yahoo, DuckDuckGo, Facebook, Pinterest, Amazon, Ahrefs |

**A filtered request returns `event_id` and nothing else** — no `visitor_id`, no Smart Signals, no
`bot_info`. That is the whole point (you aren't billed), but it means server code that reads any
other field must tolerate its absence for this traffic.

They match on the **`User-Agent` header only**, so expect both false positives and false negatives.
They are a billing control, not a security control: anything that wants through just sends a
different UA. Real bot policy is Bot Detection (`fingerprint-smart-signals`), which is a paid
Smart Signal.

**These two choices are mutually exclusive with acting on AI traffic.** If you exclude AI bots you
never receive `bot_info` for them, so you can't allow a `verified` `ai_agent` through checkout while
blocking `ai_crawler` — the per-category policy in `fingerprint-smart-signals` needs the events you
just opted out of. Decide which you want: cheaper, or able to tell them apart.

## How to apply
1. **Enumerate every origin** that legitimately loads the agent: production domain(s), any preview
   domains, and local dev. Read these from the project (e.g. deployment config, `vite.config`,
   `next.config`, CORS settings) so the allowlist matches reality and you don't lock out prod.
2. **Add them in the dashboard** — this step has no SDK call.
3. If you also use a **custom subdomain / proxy** (`fingerprint-proxy-integration`), make sure the
   allowed origins still match where the page is served from.
4. Don't over-restrict: missing a real origin silently breaks identification there. Verify each
   listed app still identifies after enabling the rules.

## Best practices
- Treat the public key as public — request filtering is the control, not secrecy.
- Keep the allowlist in sync as you add domains/preview environments.
- Never try to "hide" the public key in code; it's meant to be in the browser. The **secret** key
  is the one that must never reach the client.
- Pair with the Rules Engine (`fingerprint-rules-engine`) for signal-based blocking on top of
  origin-based filtering.
- Reach for **Exclude Search Bots** if crawler volume is inflating your bill and you have no use for
  crawler events. Leave both toggles off if you intend to make decisions about AI or search traffic
  — you need the events to do that.
