# Dependency security follow-up — 30 September 2026

This follows the [backend dependency review](compatibility.md). The remaining
issues have separate causes: a bundled native TLS library in the admin tools,
and vulnerable development dependencies in the frontend lockfile. No hosted
database, review data, reviewer identity or browser API changes are required.

## Exploration and decisions

The ADHD brainstorming workflow used three independent frames (proof,
operations and challenging assumptions), six ideas each. The available agent
capacity limited the usual five frames to three. Scores are judgment, not
security evidence: novelty / viability / fit, each out of ten, with weighted
score `0.35 N + 0.40 V + 0.25 F`.

| Cluster          | Idea                                                                            | N / V / F  | Score | Decision or trap                                                       |
| ---------------- | ------------------------------------------------------------------------------- | ---------- | ----- | ---------------------------------------------------------------------- |
| Native runtime   | ★ Checksum-verified OpenSSL/libpq, source-built Psycopg C in an admin container | 6 / 8 / 10 | 7.85  | Selected; preserve C performance and control the linked libraries      |
| Native runtime   | Hermetic native admin image                                                     | 5 / 8 / 10 | 7.50  | Same implementation family as the selected image                       |
| Native runtime   | Operational image with source-built C driver                                    | 5 / 8 / 10 | 7.50  | Same implementation family as the selected image                       |
| Native runtime   | Pinned image retained by digest for recovery                                    | 4 / 8 / 9  | 6.85  | Useful operational variation; never recover to a vulnerable runtime    |
| Native runtime   | Repair and distribute private binary wheels                                     | 7 / 5 / 7  | 6.20  | Platform-specific binary release maintenance                           |
| Runtime proof    | ★ Refuse unsafe or unidentifiable actual libpq TLS providers                    | 5 / 9 / 10 | 7.80  | Selected; host upgrades alone cannot prove what a wheel loads          |
| Runtime proof    | Startup gate before admin connections                                           | 4 / 9 / 10 | 7.45  | Same family as the selected guard                                      |
| Runtime proof    | Sanitized runtime doctor                                                        | 4 / 9 / 9  | 7.20  | Selected supporting tool; report versions without connection inputs    |
| Runtime proof    | Native inventory and real TLS connections in CI                                 | 5 / 8 / 9  | 7.20  | Selected verification                                                  |
| Runtime proof    | Rebuild plus streaming TLS regression tests                                     | 4 / 8 / 10 | 7.10  | Selected verification                                                  |
| Runtime proof    | Memory-limited malformed-certificate subprocess                                 | 7 / 5 / 7  | 6.20  | Possible follow-up; do not invent an exploit fixture from sparse notes |
| Frontend tooling | ★ Compatible patch/minor upgrades and a complete lockfile audit                 | 3 / 9 / 10 | 7.15  | Selected; keep Vitest and coverage aligned                             |
| TLS delegation   | PostgreSQL-aware TLS proxy                                                      | 7 / 4 / 5  | 5.30  | Extra network and credential boundary                                  |
| TLS delegation   | TLS-free libpq and patched sidecar                                              | 8 / 4 / 5  | 5.65  | New service to operate; local TLS still needs a safe parser            |
| New backend      | Rust COPY helper using rustls                                                   | 9 / 3 / 4  | 5.40  | A second language and rewritten database paths                         |
| New backend      | Private jobs worker and storage exchange                                        | 8 / 3 / 3  | 4.75  | New deployment and private-data transport                              |
| New backend      | asyncpg plus patched Python runtime                                             | 6 / 5 / 5  | 5.35  | Replaces tested pipeline/COPY and streaming behavior                   |
| New backend      | Go database helper and private streaming service                                | 9 / 3 / 3  | 5.15  | Extra service and credentials; unrelated to the one-page app           |

The three shortlisted approaches reinforce one another:

1. **Native admin image.** Build OpenSSL 3.5.9 and libpq 18.6 from verified source
   archives, then compile `psycopg[c]` 3.3.6 against them. Retain the existing
   Python packages and synchronous streaming/COPY APIs. Keep credentials and
   task files outside the image. The load-bearing risk is runtime linkage:
   merely compiling a patched library does not prove it supplies TLS. The first
   implementation step is a version/hash manifest. Variations include a
   container wrapper, multiple architectures, an SBOM and cached verified stages.
2. **Runtime guard and doctor.** Inspect the library selected by libpq before
   connecting and reject vulnerable, unsupported or ambiguous providers.
   Python's `ssl` version and the host's `openssl` executable are insufficient
   evidence by themselves. Preserve test connectors as explicit unit-test
   seams. The load-bearing risk is misattributing a different loaded provider;
   ambiguous loading must fail closed. The first step is centralizing the
   three production database entry points. Variations include sanitized JSON,
   immutable artifact evidence and strict local synthetic-test validation.
3. **Frontend tooling repair.** Upgrade Vitest and coverage together, then
   refresh the three vulnerable transitive packages inside their existing
   parent constraints. Inspect the entire lockfile rather than only root
   dependencies. The load-bearing risk is leaving a vulnerable nested copy or
   incompatible Vitest peer. The first step is mapping each installed package
   to its parent. Variations include scoped overrides only if necessary, a
   complete development audit and a CI gate against newly published advisories.

The provocation that changed the plan: a current Python package version can
still deliver yesterday's vulnerable TLS library. Patch the native runtime and
prove its loaded provider, rather than treating package freshness as proof.

## Phase 1: frontend tooling

| Package                                       | Previous | Selected | Security and compatibility evidence                                                                                                                                                         |
| --------------------------------------------- | -------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Vitest, coverage and internal Vitest packages | 4.1.10   | 4.1.11   | [Mock redirect path traversal](https://github.com/advisories/GHSA-82fw-gwwq-j7x9); exact coverage peer retained                                                                             |
| brace-expansion, through ESLint/minimatch     | 5.0.8    | 5.0.12   | Four CPU/memory/recursion DoS fixes; existing minimatch range accepts it                                                                                                                    |
| nanoid, through Vite/PostCSS                  | 3.3.16   | 3.3.19   | [Zero-size generator loop](https://github.com/advisories/GHSA-2v37-7h3g-55p8), async correction and excessive-size handling                                                                 |
| undici, through jsdom                         | 7.29.0   | 7.30.0   | Includes all ten [7.29.1 security fixes](https://github.com/nodejs/undici/releases/tag/v7.29.1) and [7.30.0 fixes](https://github.com/nodejs/undici/releases/tag/v7.30.0); no major upgrade |

GitHits package information, batched upgrade reviews, release histories and
tagged source informed these choices. Package advisory summaries were
incomplete for Undici; the upstream security release lists ten fixes covering
TLS-option preservation, WebSocket failures, cookie caching, decompression,
retry, cache methods and dump limits. Ordinary decompression now defaults to
64 MiB per stage. VeriTaxa's browser uses native browser networking; Undici is
used by development jsdom. This distinction does not excuse leaving tooling
vulnerable.

Sparse brace-expansion release notes required
[source inspection](https://github.com/juliangruber/brace-expansion/blob/v5.0.12/src/index.ts):
comma parsing is iterative; expansion has limits of 100,000 results, four
million total characters, 1,000 nested levels and 1,000 rewrites. Ordinary
project globs remain supported; pathological patterns may be truncated or
rejected. The existing parent ranges accept all three transitive updates, so
no overrides or frontend framework changes are needed.

Compatible Vitest helpers also moved: es-module-lexer 2.3.2, obug 2.2.1,
std-env 4.3.0, tinyexec 1.3.1 and tinyrainbow 3.2.0. Batched GitHits reviews
found no added direct or transitive advisories or changed dependency constraints.

Validation: a clean `npm ci`, all 100 unit tests, lint, TypeScript, production
build and production zoom/pan browser checks pass. The complete npm audit reports
zero vulnerabilities. Formatting, the private-data scan and whitespace checks
pass before this phase's commit.

## Phase 2: native OpenSSL remediation

The Psycopg 3.3.6 binary wheel uses OpenSSL 3.5.8. The
[29 September advisory](https://openssl-library.org/news/vulnerabilities-3.5/#CVE-2026-35189)
describes certificate-processing memory pressure affecting TLS clients before
3.5.9. Updating the system library does not replace a wheel's bundled library.
The selected design follows Psycopg's
[production installation guidance](https://github.com/psycopg/psycopg/blob/3.3.6/docs/basic/install.rst#L163-L196)
for a C implementation linked to separately maintained libpq/OpenSSL.

`psycopg[binary]` has been replaced with `psycopg[c]` in the manifest and lockfile;
the bundled binary distribution is no longer installed. The admin image builds
the two native libraries from the exact URLs and SHA-256 hashes in
`admin/native-deps.json`. The Python base image is pinned by digest. The
deny-by-default build context excludes credentials, private tasks and exports;
operators supply them only at runtime.

All three production database entry points use `connect_admin`. Optional Auth
provisioning checks the same runtime before HTTPS access. The Linux inspector
resolves TLS/version symbols through the loaded driver and Python HTTPS
extension, checks their supplying libraries, and rejects multiple mapped
providers. It does not trust a shell executable, Python compile-time version
constants or a package name. Static or unsupported linkage fails closed.
`python -m tools.native_runtime --json` reports only version evidence and status.

The reviewed policy accepts the OpenSSL 3.5 line from 3.5.9 and libpq 18 from
18.6, with the C driver. New release branches require review. An unsafe remote
connection cannot bypass the guard with `sslmode=disable`. The sole exception
requires numeric loopback, one of the two named disposable fixture databases,
explicit `sslmode=disable` and `gssencmode=disable`, and no service, hostaddr,
multi-host or `PG*` environment redirection. Local TLS is still checked.

Validation: checksum verification and the complete native source build pass.
The loaded C driver reports libpq 18.6 and OpenSSL 3.5.9; Python HTTPS resolves
the same provider. All 171 backend tests pass, including all 36 real-driver
import/export tests over `sslmode=verify-full`. Guard tests cover vulnerable and
unreviewed branches, provider ambiguity and connection redirection. Ruff, frozen
lockfile checks, formatting, the private-data scan and whitespace checks pass.
Local Docker socket access is unavailable, so the complete container recipe is
verified by the CI phase; the local native build tests the same build script.
The default managed Python's statically linked HTTPS extension is deliberately
rejected rather than misreported as patched by a host library update.

## Phase 3: regression checks

CI audits the complete npm dependency tree, including development tooling, and
fails on newly reported advisories. A separate `admin-runtime` job builds both
the production image and a test image, probes the final production runtime after
loading Polars/PyArrow, and checks installed Python dependency compatibility.
It creates an isolated PostgreSQL TLS fixture and runs all backend tests with
certificate verification enabled. Generated keys and fixture data are transient
and are not published or committed.

Four opt-in native TLS tests compare the actually loaded libraries with the
source manifest, exercise COPY and streaming over verified database TLS,
reject an unrelated CA, and exercise Python HTTPS against a local synthetic
server. Local validation passes all 175 backend tests, all 100 frontend unit
tests, the full npm audit (zero vulnerabilities), lint and formatting. CI uses
the container to verify the remaining image-build boundary that cannot run
through the local Docker socket.

Native version floors, source versions/hashes, the base image digest and Python
lockfile must be reviewed together in later dependency updates. An npm advisory
audit cannot detect OpenSSL embedded in a Python interpreter or native wheel.
