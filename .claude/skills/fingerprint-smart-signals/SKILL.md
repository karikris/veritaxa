---
name: fingerprint-smart-signals
description: Use the full set of Fingerprint Smart Signals (bot detection with bot_info — name, provider, category, identity, confidence — plus VPN, proxy, tampering, incognito, IP blocklist, velocity, suspect score, location spoofing, and more) from the v4 Server API to make richer server-side trust decisions. Use after the basic identification + verification is in place, when you want detailed insights about a visitor beyond confidence.
---

# Fingerprint — Smart Signals (v4 Server API)

Maps to the dashboard **"Access detailed insights about a visitor"** Get Started step. Once your
backend fetches an event server-side, the same `getEvent(eventId)` response carries 100+ signals.
This skill is about *acting on the full set*, not just `confidence`. All of these are
server-verified — never trust client-reported equivalents.

## Prerequisite
A working server-side flow (in whatever backend you run) that already calls `getEvent(eventId)`
with your `FINGERPRINT_SECRET_API_KEY`.

## Signals (flat v4 event shape)
Each Smart Signal is a top-level field on the event. The web-relevant set:

| Field | Meaning | Typical action |
| --- | --- | --- |
| `bot` | `"bad" \| "good" \| "not_detected"` — the coarse verdict | See **Bot detection** below; don't act on this field alone |
| `bot_info` | object — `name`, `provider`, `category`, `identity`, `confidence` | Who the bot is and whether its identity checks out |
| `bot_type` | string — e.g. `"headless_chrome"`, `"chatgpt_agent"` | Finer classification of the automation |
| `vpn` | behind a VPN | Step-up / score for high-risk flows |
| `proxy` | behind a public proxy | Step-up / score |
| `tampering` | bool — anomalous browser signature / anti-detect browser | Reject for sensitive actions |
| `incognito` | private browsing | Score; don't hard-block alone |
| `ip_blocklist` | object: `attack_source`, `email_spam`, `tor_node` (IP on known-malicious lists) | Block or step-up on any sub-flag |
| `velocity` | object of interval counts (`5_minutes`/`1_hour`/`24_hours`) per visitor/IP/linked_id | Rate-limit abuse / ATO |
| `suspect_score` | integer — weighted aggregate of Smart Signals | Threshold-based routing |
| `location_spoofing` | GPS/timezone spoofing | Score for geo-gated actions |
| `developer_tools` | devtools open | Score for scraping/automation |
| `virtual_machine` | running in a VM | Score |
| `raw_device_attributes` | low-level device attributes | Custom heuristics |

> Field availability depends on your plan and platform (web vs. mobile), so guard each access
> (`event.vpn ?? false`) so a missing signal doesn't throw. Every field is specified in the v4
> Server API reference: https://docs.fingerprint.com/reference/server-api-get-event (source:
> https://github.com/fingerprintjs/openapi, also served as the Fingerprint MCP event-schema
> resource).

## Bot detection
> Docs: https://docs.fingerprint.com/docs/bot-detection/overview (covers AI tools and traditional
> automation alike) · https://fingerprint.com/bot-directory/ (which bots are recognized).
>
> Bot Detection needs **Pro Plus or Enterprise**, and the AI-tool fields need **Server API v4+**.

`bot` is a verdict, not a description: three values can't separate Googlebot from ChatGPT's agent
from Playwright, and every one of those needs a different answer. Read `bot_info` — present on every
event where a bot was detected, absent otherwise.

> If `bot_info` is missing for traffic you know is a crawler, check **Security → Bots** first: the
> **Exclude AI Bots** / **Exclude Search Bots** toggles drop those requests before they're billed and
> return `event_id` alone. See `fingerprint-request-filtering`.

| `bot_info` field | Values | |
| --- | --- | --- |
| `name` | `"Googlebot"`, `"GPTBot"`, `"ClaudeBot"`, `"ChatGPT-User"`, `"Browserbase Agent"`, `"ChromeHeadless"` | the specific bot |
| `provider` | `"Google"`, `"OpenAI"`, `"Anthropic"`, `"Browserbase"`, `"chromium/chromium"` | who operates it |
| `category` | `search_engine_crawler`, `ai_crawler`, `ai_agent`, `ai_assistant`, `ai_browser`, `ai_search`, `browser_automation`, `scraping`, `monitoring_and_analytics`, `security`, `advertising_and_marketing`, `aggregator`, `ecommerce`, `search_engine_optimization`, `other`, `unknown` | what it's *for* — the axis most policies should key on |
| `identity` | `verified` \| `signed` \| `spoofed` \| `unknown` | whether the claim holds up |
| `confidence` | `low` \| `medium` \| `high` | how sure the classification is |

`name`, `provider`, `category`, `identity` and `confidence` are all present when `bot_info` is;
`provider_url` is optional. A real event:

```json
{ "bot": "bad", "bot_type": "headless_chrome",
  "bot_info": { "name": "ChromeHeadless", "provider": "chromium/chromium",
                "category": "browser_automation", "identity": "unknown", "confidence": "medium" } }
```

**`identity` carries the most policy weight and has no equivalent in `bot`**
(defined at https://docs.fingerprint.com/docs/ai-agents, which is the fullest prose on it):
- `verified` — signature verified *and* the bot is operated exclusively by its vendor. Googlebot
  really is Googlebot. Allow.
- `signed` — signature verified against the agent's public key directory (Web Bot Auth), but run by
  the provider's customers rather than the provider. Allow.
- `spoofed` — presented an identity that **failed** verification. Not automatically malicious: a
  misconfigured Web Bot Auth setup lands here too, so investigate before making it a permanent
  block — but never treat it as trusted.
- `unknown` — recognized as a bot, but presented no verifiable identity. Most headless automation
  lands here; apply your own logic.

### Deciding
- **Never blanket-block `bot !== "not_detected"` on a crawlable route.** That set includes `good`,
  and blocking a `verified` `search_engine_crawler` is an SEO outage. Failing closed on *any* bot is
  right for login/checkout/password-reset, where no crawler belongs — scope it to those.
- **Never trust `identity === "spoofed"`,** but check whose bot it is before blocking permanently —
  a customer's broken Web Bot Auth signature produces the same result as an impersonator.
- **`bot === "bad"` with no `bot_info`** means automation Fingerprint doesn't recognize — nothing to
  allow-list against, so review or block.
- **Choose the AI categories deliberately, per route.** `ai_crawler` / `ai_search` are a
  licensing-and-robots question; `ai_agent` / `ai_browser` / `ai_assistant` are automation acting for
  a real logged-in human, which you may well want to let browse and stop at checkout. Answering
  "is it a bot" doesn't answer either of these.
- **Check `confidence` before anything irreversible.** A hard block on a `low`-confidence
  classification is a false-positive machine.
- The `bot_info` object itself is closed (`additionalProperties: false`), but the **`category`
  enum is not stable** — the AI values (`ai_agent`, `ai_browser`, `ai_crawler`, `ai_search`,
  `ai_assistant`) were added months after `bot_info` shipped. Treat an unrecognized category as
  `unknown` rather than as "not a bot", or the next addition silently becomes an allow.
- All five fields are also **Rules Engine conditions** (Bot Category, Bot Identity, Bot Confidence,
  Bot Name, Bot Provider), so this policy can be expressed no-code instead — see
  `fingerprint-rules-engine`.

## How to apply
1. **Don't gate on a single signal.** Combine them into a per-action policy: e.g. block on
   `bot_info.identity === "spoofed"`, `bot === "bad"` or `tampering`, step-up auth on
   `vpn || proxy || ip_blocklist`, and log `suspect_score` for analytics.
2. **Tune by action risk.** Login/checkout/password-reset warrant strict, fail-closed policies;
   read-only or low-risk actions can score-and-allow.
3. **Use `velocity` for abuse/ATO.** A spike of identifications for one `visitor_id` (or many
   visitors hitting one account) is a strong takeover/credential-stuffing signal.
4. **Persist signal outcomes** alongside your own fraud events so you can iterate on thresholds.
5. **Smart Signals require enablement.** Some are off by default in the workspace — enable them in
   the dashboard (Smart Signals settings) for the environment whose secret key you use.

## Best practices
- Server-side only — Smart Signals are never trustworthy when reported by the client.
- Fail closed on lookup errors for high-risk actions.
- Don't log the raw secret key or full event payloads containing PII.
- Re-evaluate signals on **every** sensitive action; each `event_id` is single-use.

See `snippets/signals-policy.js` for a composable scoring helper.
