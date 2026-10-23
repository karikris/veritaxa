---
name: fingerprint-proxy-integration
description: Serve the Fingerprint JS Agent (v4) from your own domain, Fingerprint's required production setup — a first-party custom subdomain (set up by the Fingerprint CLI wizard, `fingerprint integrate --subdomain`, the `fingerprint subdomains` commands, or the dashboard) or a proxy integration (Cloudflare, CloudFront, Azure Front Door, Akamai, Fastly), configured through the v4 `endpoints` option. Use after basic identification works, when identification is unreliable, short-lived or missing for some visitors in production.
---

# Fingerprint — First-party deployment (custom subdomain / proxy)

Fingerprint's production setup serves the JS Agent from **your own domain**, through a custom
subdomain or a proxy integration. The docs call this **required for correct identification**. By
default the agent loads from, and sends requests to, Fingerprint's domain, a third-party context
for your site. Browsers restrict third-party storage (Safari's ITP, Firefox's ETP, storage
partitioning generally), so identification from that context is shorter-lived and inconsistent,
and for some visitors it fails outright, which means no fraud check runs for them. Serving the
agent first-party fixes this. In the dashboard this step is listed under *Protect against ad
blockers*.

## Scope and consent
This changes **where requests go**, not what you are allowed to collect. It is for a site you
operate, and it does not reduce any disclosure obligation you already have.

- Use it only on **domains you own or operate**, to identify visitors to *that* site.
- Keep it purpose-limited to **security, fraud prevention and abuse detection**. It is not a
  mechanism for advertising, ad targeting, audience building, or profiling people across sites you
  don't control.
- **Disclose device identification in your privacy notice**, and obtain consent where the law that
  applies to your users requires it (e.g. GDPR/ePrivacy, CCPA/CPRA). Moving the endpoint to your
  own domain does not change this; confirm the specifics with whoever owns privacy compliance at
  your company.
- **Honour opt-outs and deletion requests.** Don't use first-party deployment to re-identify
  someone who has opted out, or to work around a choice a user has expressed.

> **This API changed in v4.** The old `scriptUrlPattern`, `endpoint` (singular), `tlsEndpoint`, and
> `disableTls` options were **removed** and consolidated into a single **`endpoints`** option.
> Docs: https://docs.fingerprint.com/docs/custom-subdomain-setup ·
> https://docs.fingerprint.com/docs/protecting-the-javascript-agent-from-adblockers

## Pick one approach

| Approach | Who runs it | Effort | Pick it when |
| --- | --- | --- | --- |
| **Custom subdomain** | Fingerprint, behind DNS records on your domain | Low: add the returned DNS records | Default. Any plan. Set up from the CLI or the dashboard. |
| **Proxy integration** | You, at your edge (Cloudflare on any plan; CloudFront, Azure Front Door, Akamai, Fastly on Enterprise) | Higher: deploy and maintain a proxy | You need Safari cookie lifetime of one year instead of seven days, IPv6, unlimited subdomains and paths, or WAF/logging on identification traffic |

Never set up both for the same app. Both change only where the agent loads its script from and the
`endpoints` value, not your application logic, so you can start with a subdomain and move to a
proxy later.

## The v4 `endpoints` option
- `endpoints` sets where the agent **sends identification requests**. It takes a single string
  (your subdomain/proxy origin); an array can be supplied when fallbacks are required.
- The **script download URL** is set separately:
  - **CDN**: it's the import URL — `https://metrics.yourdomain.com/web/v4/<PUBLIC_API_KEY>`. Note
    the `/web/` segment: on your own host the agent download sits under that prefix, while
    Fingerprint's CDN serves it at `https://fpjscdn.net/v4/<PUBLIC_API_KEY>` with no prefix. So
    routing an existing CDN import through a subdomain means adding `/web/`, not just swapping the
    host. (Passing `endpoints` to the npm/SDK path appends `/web/` for you.)
  - **NPM / framework SDKs**: pass `endpoints` to the provider/start options (e.g. the
    `FingerprintProvider` `endpoints` prop). See `snippets/subdomain-options.js`.
- If the site has a Content Security Policy, add the subdomain or proxy origin to `connect-src`.

## Custom subdomain

A subdomain is usable only at server status `active`. Creating it, adding its DNS records, and
even all records reading `validated` are not enough. Only `active` permits setting `endpoints` or
switching the script URL. DNS and certificate issuance take minutes to hours (the docs allow up to
24 hours), so a pending setup ends the run with a clear next step, never a polling loop.

Use the available Fingerprint MCP tools, the CLI wizard, the `fingerprint subdomains` commands,
or the dashboard. They manage the same workspace resources: reuse an existing subdomain rather
than creating another. An MCP connection does not imply a CLI login or that every tool is enabled.

### The Fingerprint MCP

Use the subdomain tools directly when they are in your tool list; otherwise `list_tools` names
the route (`call_tool` for reads, `call_write_tool` for create, connect and verify, which need the
user's approval either way). If a tool is unavailable, use the CLI when there is a shell, or the
dashboard. Never ask for a Management API key: the MCP is already authenticated.

- List before creating: `list_subdomains` is paginated, follow `next_cursor` to find the exact
  hostname. `get_subdomain`, `connect_subdomain` and `verify_subdomain` take an `id` or a `hostname`.
- Adding the records, in this order: try `connect_subdomain` first. It returns a Domain Connect
  link; give it to the user to open in their browser, where they approve the records at their DNS
  provider and land on the Fingerprint dashboard. Wait for them to say they are back, then verify.
  A 409 means the provider has no Domain Connect or the subdomain is no longer pending: present the
  records as in [DNS records](#dns-records) instead, for the user or an authorized DNS-provider
  tool to add. On Cloudflare, DNS only (proxying off).
- Verify once after DNS changes, then `get_subdomain` for status. On 429 respect
  `error.retry_after`; on 422 show `error.violations`. Pending is not a failure: report hostname,
  id and what remains, and stop. Only `active` permits app changes ([Branch on status](#branch-on-status)).

The MCP does not expose deletion; for that use the CLI or the dashboard.

### The CLI wizard

The `npx fingerprint` wizard offers this step once identification works. To start it directly, or
to pick up a pending one where it stopped:

```bash
npx fingerprint integrate --subdomain metrics.yourdomain.com
```

The CLI asks for the hostname (it never guesses one), looks it up in the workspace and creates it
if missing. When the domain's DNS provider supports Domain Connect (Cloudflare today), it offers
to open the provider in the browser and let it add the records with one approval; otherwise, or
if the user prefers, it prints the records and offers **Check the DNS records now** (each check
waits up to five minutes for propagation), **Show the DNS records again**, or **Finish later**.
Once the subdomain is `active`, the CLI asks whether to update the app. The agent edits the provider
options, and the CLI writes the endpoint variable to the frontend's env file itself. Unfinished
setup is remembered per project, including an active subdomain whose app update was declined;
the next `fingerprint integrate` run offers to resume it. With `--ci` or `--yes` the
CLI skips confirmation and exits with the records and resume command if the subdomain is pending.

**When you are the agent running inside the wizard**, follow the CLI's prompt. If it supplies a
hostname verified as `active`, skip resource creation, DNS and verification: only update the
application's integration. Reference the endpoint variable the CLI names in the provider/start
options; the CLI writes it. If no variable is supplied, use the endpoint directly. Never ask for
a Management API key, read `.env`, or start another CLI flow. A comment or an unused variable
does not configure the app — update the options used by the existing integration.

### The `fingerprint subdomains` commands

The same operations as commands, for an agent with a shell or a user at a terminal. Sign in once
with `fingerprint login`; the CLI keeps a workspace-scoped key in the user's config directory and
the commands read it. Every command accepts the hostname or the `certv2_…` id and `--json`.

```bash
fingerprint subdomains                                  # list, plus the available commands
fingerprint subdomains create metrics.yourdomain.com    # register; prints the DNS records
fingerprint subdomains list
fingerprint subdomains get    metrics.yourdomain.com    # status + DNS records, no side effects
fingerprint subdomains verify metrics.yourdomain.com    # one on-demand DNS check, then fresh status
fingerprint subdomains connect metrics.yourdomain.com   # Domain Connect: the provider adds the records, then verify
fingerprint subdomains delete metrics.yourdomain.com    # prompts; --yes required with --json or --ci
```

Errors come back as `{ kind, message }` (plus `violations` or `retry_after` when present). Surface
them and stop; they are already actionable:

| `kind` | Meaning |
| --- | --- |
| `not_authenticated` | run `fingerprint login` |
| `invalid_subdomain` | the returned `violations` say what to change |
| `duplicate` | the hostname exists; resolve it with `get` instead |
| `not_found` / `ambiguous` | no match / several match; use `list` and pick by id |
| `limit_reached` | 50 subdomains per workspace, 5 on a free trial |
| `rate_limited` | the API allows one verify per minute; wait `retry_after` |
| `confirmation_required` | `delete` needs `--yes` in `--json` or `--ci` runs |
| `unsupported` | no Domain Connect for this provider, or the subdomain is no longer pending; add the records by hand |
| `declined` / `timeout` | the user did not approve at the provider, or did not come back in time; the records are still to be added |
| `unavailable` / `api_error` | service unavailable or unexpected; report and stop |

Never retry in a loop, never delete to make room, never ask the user to paste a key, and never
call the Management API over raw HTTP from a skill run.

### The dashboard

The user registers the subdomain and adds the records themselves, and you do the code:

1. **Settings → Subdomains → New subdomain**, enter the hostname (or open the existing one).
2. Add the records the dashboard shows at the DNS provider, all at once (**Copy all records** is
   zone-file format). On Cloudflare DNS the dashboard offers **one-click setup** via Domain
   Connect; either way the records must be **DNS only** (proxying off), and CNAME flattening off.
3. **Check DNS records**, then wait for the status to read **Active**.
4. Only then apply [How to apply](#how-to-apply-code-side). Ask the user to confirm **Active**
   before editing.

### Choosing the hostname

Confirm the exact hostname with the user before creating anything: subdomains are immutable, so
changing one means deleting and recreating it. Constraints, enforced by the API:

- A subdomain of the site the app runs on (e.g. `metrics.yourdomain.com` for `yourdomain.com`),
  never the site's own hostname (its A records will point at Fingerprint) and never a subdomain
  of some other domain the user owns: that is not first-party for this site.
- A valid FQDN, at most 64 characters, not containing `fingerprint` (case-insensitive). The docs
  also advise against `fp`. Use a neutral name such as `metrics`.
- 50 per workspace, 5 on a free trial.

### DNS records

`dns_records` holds `routing[]` (two A records) and, when needed, `caa`. New subdomains use HTTP
certificate validation: `verification` is a validated placeholder with empty `host` and `value`;
do not display or add it. Older subdomains can still return a real verification CNAME: keep it.
Each record has `type`, `host`, `value` and its own `status` (`pending_validation`, `validated`,
`failed`). Show the real records together: the A records do not wait for the certificate. The
user adds them at their DNS provider, which may not be their web host; if you have an authorized
DNS-provider tool, offer to apply exactly these records after the user approves.

### Branch on status

Status comes from the server, never from elapsed time or from the records.

| Status | Action |
| --- | --- |
| `pending` | Leave `endpoints` and code untouched. Name the records still `pending_validation`; when all are `validated`, say certificate issuance is in progress. End as waiting: no polling, no second verify. Report hostname, id, what is outstanding, and the resume command. |
| `active` | Configure the endpoint (below). |
| `expired` | The certificate has expired. Do not wait for DNS or configure the app. Offer to delete and recreate the subdomain; both need explicit approval. |
| `timed_out` | Records were not validated within 14 days. Offer to delete and recreate the same hostname; both need explicit approval. Then present the new records. |
| `failed` | Records were found but the certificate cannot be issued, almost always a conflicting CAA record. Show the `caa` record to add; once it has propagated, delete and recreate. Both need approval. |

Get Started step 3 stays open while the subdomain is anything but `active`.

### Configure only after `active`

Follow [How to apply](#how-to-apply-code-side). Inside the wizard, reference the env variable the
CLI names and stop; the CLI writes it. Elsewhere, never read or print `.env`; if you cannot write
the env file, give the user the exact variable and value. For a CDN install, switch the import URL
and `endpoints` directly. Keep the public key and region as they are.

## Proxy integration
1. Deploy one of Fingerprint's proxy integrations at your edge: **Cloudflare** (dashboard wizard,
   any plan), **AWS CloudFront**, **Azure Front Door**, **Akamai**, **Fastly VCL** or **Fastly
   Compute** (integration guides, Enterprise). It forwards a path on your domain to Fingerprint
   with your proxy secret.
2. Create the **proxy secret** (an API key of type `proxy`) in the dashboard and configure it in
   the proxy.
3. Set `endpoints` to your proxy origin. Same code shape as the subdomain case; only the URL
   differs. Host the proxy on the same registrable domain as the site, and on the same cloud
   provider where you can: Safari limits cookie lifetime when the site and proxy IP ranges differ.

## How to apply (code side)
- The only code change is in the **provider/start options** where you already pass the public key
  and region: add `endpoints` pointing at your subdomain/proxy. See `snippets/subdomain-options.js`.
- Keep the value in an env var named `FINGERPRINT_ENDPOINTS` with the same client prefix the public
  key uses (`NEXT_PUBLIC_`, `NUXT_PUBLIC_`, `VITE_`). That is the variable the CLI writes, so
  dev/staging/prod can differ without code edits.
- Region still must match the workspace region.
- Verify in the browser devtools Network tab that agent requests now go to **your** domain and
  return 200.

## Best practices
- Prefer the subdomain for a fast first step; move to a proxy when you want to own the edge.
- Don't expose the proxy secret to the browser; it lives only in your edge proxy config.
- If a request to your subdomain/proxy fails, the agent can fall back to Fingerprint's default
  endpoints; still handle identify errors so the flow degrades gracefully.
- Deleting an `active` subdomain stops its traffic immediately; repoint the agent first.
- Point the subdomain at your own infrastructure only. Don't route another party's traffic through
  it, and don't reuse it for anything beyond the identification described in your privacy notice.
