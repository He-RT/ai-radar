# Source registry operational notes

The catalog contains exactly 500 auditable entries. In version 3, 447 are
scheduled and 53 use the deliberately non-scheduled `manual` connector, which
becomes a terminal runtime `policy_skip`. Manual entries are disabled, carry a
machine-readable reason, and are retained for provenance and review; the
collector must not bypass a login, paywall, robots policy, or TLS failure.

The 50 `reg-*` entries remain in a policy-review lane until each endpoint has a
documented robots, terms, and extraction decision. Three other endpoints are
explicitly policy-skipped pending a fresh access check:

| Source ID | Reason recorded on 2026-08-12 | Restore condition |
| --- | --- | --- |
| `media-46` (`aigcopen.com`) | TLS certificate verification failed | A normal public HTTPS GET succeeds with certificate verification enabled. |
| `media-50` (`paperweekly.site`) | TLS connection ended unexpectedly | A normal public HTTPS GET completes reliably. |
| `fp-alibaba-2` (`bailian.console.aliyun.com`) | Console-style endpoint may require access control | A public, unauthenticated endpoint is documented and reviewed. |

GitHub repository roots and `/releases` are separate signals. A repository root
uses the single-repository API for metadata such as `pushed_at`; a release URL
uses the releases collection. The validator permits at most one of each per
canonical repository, so two catalog entries never share a dispatch operation.

Priority and scheduling are coupled: P0/P1/P2/P3 intervals are at most
10/30/60/360 minutes. Raw public webpages use the 30-day default retention;
official public GitHub metadata uses 90 days. Every entry records the basis,
while hashes, response metadata, necessary excerpts, and structured facts may
remain after raw payload expiry.

The 2026-08-12 remediation used redirect-following, lightweight public GETs.
Representative checks returned HTTP 200 for the replacement Mistral AI
Technology, Cohere Research, Perplexity API documentation, TechRadar AI,
Engadget AI, The Register AI, The Next Web AI, and sampled replacement GitHub
repositories from OpenAI, Anthropic, Google, Qwen, and DeepSeek. No feed URL
was inferred or invented. A non-200 result during this audit never authorizes
an access-control workaround; record it as `manual`/`policy_skip` instead.
