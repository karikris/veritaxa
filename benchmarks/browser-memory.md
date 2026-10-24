# Real-raster browser memory gate

Run from the repository root on Linux with Node 22.12+, OpenSSL and the pinned
Playwright Chromium installation. No database, Supabase credentials, real images
or private review records are used.

```sh
npm run browser:memory:check
npm run browser:memory:gate -- --output /tmp/veritaxa-browser-memory.json
```

The output must not already exist. The gate runs desktop, draft-heavy desktop
and mobile-pressure profiles three times each, sequentially, in fresh Node and
Chromium processes. Each navigates 1,000 times, including wrap-around, and samples
at positions 0, 100, ..., 1,000. CI publishes the aggregate JSON, not browser
profiles, keys, traces or generated images. A 180-second worker deadline fails
the gate and stops that worker's owned process group. The suite stops on the first
terminal worker failure, keeping the original cause rather than reporting only
a missing final JSON file.

For a short **non-passing pilot**, or a negative control:

```sh
npm run browser:memory -- --steps 10 --output /tmp/veritaxa-browser-pilot.json
npm run browser:memory -- --profile control --output /tmp/veritaxa-image-control.json
npm run browser:memory -- --profile control --record-network --output /tmp/veritaxa-recording-control.json
```

## What is exercised

Vite compiles the production application/view/domain code with a synthetic
navigation adapter. The adapter generates one item on demand, not an artificial
1,000-item browser queue, and refuses database writes. Existing browser tests
separately cover saves, retries, conflicts, authentication ownership and errors.
The image-only control does not include application code.

A loopback HTTPS server creates distinct 1,600 × 1,067 RGBA PNG previews and
3,200 × 2,134 source images. The probe waits for exact natural dimensions, decode
completion and two animation frames before moving on. HTTP and decoded-image
caches remain enabled; there is no request interception, cache flush, image
mirror or application-owned preloading. Source inspection is exercised explicitly
after the navigation soak, followed by return to the cached preview. The server
counts requests to verify that no source loaded automatically and that returning
to the preview did not fetch it again.

Draft-heavy profiles enter a label and a substantial Unicode comment on every
image. From the 256th attempted dirty navigation onward they explicitly discard
the current draft when capacity blocks movement. Exactly 745 such decisions are
required across 1,000 navigations; older parked drafts are not silently evicted.
The warm-up ends at navigation 300, after the draft store has reached capacity.

## Measurements and limits

- JavaScript heap before and after explicit garbage collection, plus retained
  document/node/listener counts. Sampled heap must stay below 16 MiB and retained
  DOM counts must stay unchanged.
- Linux RSS and PSS for the browser and its descendants, before and after GC.
  Children of every thread are included, not only those of its thread leader.
  Node, the PNG server and Vite are excluded. RSS counts shared mappings more
  than once; PSS apportions them across processes.
- Chromium detailed native memory dumps, including `cc/image_memory`, GPU shared
  images, partition allocations and other named roots. These are allocation
  accounting, **not additive resident-memory totals**: parent/child entries and
  shared mappings overlap. Discardable allocations can remain accounted for
  after their resident pages have been released.

Across checkpoints 300–1,000, both the increase between early/late three-sample
medians and fitted total growth must stay within the following tolerances:

| Measurement                     | Maximum retained growth |
| ------------------------------- | ----------------------: |
| JavaScript heap                 |                   1 MiB |
| Browser-process PSS             |                  64 MiB |
| Browser-process summed RSS      |                 128 MiB |
| Decoded-image accounting        |                  32 MiB |
| GPU shared-image accounting     |                  16 MiB |
| Partition allocation accounting |                   4 MiB |

These are regression tolerances, not a mathematical proof of zero leaks. Native
tolerances allow browser allocator/cache variation; the stricter heap, DOM and
partition checks also detect visited-item retention. Missing/nonfinite metrics,
incomplete navigation, unexercised draft capacity and contaminated network
recording cannot pass. Individual samples and both growth calculations remain
in the report for inspection, including pre-GC/process-pressure peaks.

The mobile-pressure profile uses Pixel 7 viewport/user-agent/touch emulation,
a 64 MiB V8 old-space limit and a critical memory-pressure notification every
100 navigations, with a 200 ms settling interval before retained measurements.
This is **not a physical low-RAM phone or a total-process RAM cap**. Native browser
cache budgets also depend on the host. Unrestricted source images, and the first
decode of an incorrectly declared preview, remain outside a hard memory bound.

## Dump validation, recovery and failure evidence

Each checkpoint and explicit source-inspection measurement records a
`measurementAttempts` entry with its profile, navigation, phase, attempt number,
collection stage, dump GUID, request success, trace completion, data-loss flag,
allocator-dump count, and required allocator values. Conditions distinguish
`request_failed`, `trace_data_loss`, `no_allocator_dumps`, `missing_allocator`,
`invalid_allocator`, `malformed_response`, `malformed_trace`, `trace_timeout`,
`cdp_timeout`, and `cdp_error`. Invalid numeric entries and transport/cleanup
errors retain their details. Chromium hierarchy-only allocator nodes without a
size are skipped; aggregate image, GPU and partition metrics must still exist
and contain finite nonnegative byte counts. A measured zero is valid.

A completed trace with an unsuccessful dump, lost data, no allocator dumps or
missing required metrics gets one retry after 250 ms at the same checkpoint.
Each attempt uses a fresh trace and accumulator. Both attempts remain in the
report; only a valid result supplies the sample. Persistent incompleteness fails.
Crashes, timeouts, transport errors, malformed values and memory-growth failures
never receive a retry. Browser caches, GC policy, the 8 MiB trace buffer, memory
tolerances and the worker deadline are unchanged.

When `--output` is supplied, a private `<output>.progress.json` sidecar is
reserved exclusively and replaced atomically after each sample and at the start
and end of each dump attempt. It contains completed samples, current navigation,
last checkpoint, collection phase, attempt diagnostics, original failure and
cleanup errors. Keep both the report and sidecar for standalone investigations;
use a new output path on each invocation. An abrupt kill can leave the last
completed checkpoint and an in-progress attempt instead of a final error.

The aggregate CI artifact preserves the existing `runs`, `failures` and `limits`
fields and adds `workerFailures`. Failed-worker evidence includes its profile,
repeat, exit code, terminating signal, deadline status, bounded stderr tail,
report-read errors and available progress. Full traces, browser profiles and TLS
keys are not published. Recovered dump attempts remain visible inside successful
run reports. Recovery is not evidence that an application memory leak was fixed.

## Avoiding measurement-induced retention

Playwright's normal browser driver enables network recording. A real-raster
1,000-navigation investigation found stable application heap/DOM but roughly
190 MiB of partition allocation accounting. The image-only control reproduced
the growth. With a direct browser connection and no network recording, this
allocation pool stayed around 5–7 MiB. Enabling `Network.enable` on the direct
image-only control reproduced growth from 70.70 MiB at navigation 300 to
202.31 MiB at navigation 1,000. This control isolates recording-related native
retention from application state.

The harness therefore uses a small direct CDP transport and only imports
Playwright's pinned executable location/device descriptors. The recording control
is deliberately marked contaminated and is not accepted by the nine-run gate.
It does not disable actual HTTP caching to obtain a smaller result.

Tracing uses an 8 MiB buffer, requires a successful detailed dump and checks for
data loss. The default trace buffer is much larger; see the primary
[Tracing protocol](https://chromedevtools.github.io/devtools-protocol/tot/Tracing/).
Pressure notifications are explicitly synthetic; see the
[Memory protocol](https://chromedevtools.github.io/devtools-protocol/tot/Memory/).
Temporary TLS keys and fresh browser profiles live in private temporary
directories and are removed on completion.
