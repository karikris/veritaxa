# VeriTaxa agent notes

VeriTaxa is a private-task, public-code image triage application.

- Never commit real review tasks, source image URLs, reviewer emails, credentials, or exports.
- Keep source metadata out of reviewer-facing RPC responses and browser state.
- Browser code may use only the Supabase URL and publishable key.
- Keep the application one page, framework-free, and taxon-independent.
- Run focused tests, the data-leak scan, and `git diff --check` before committing.
- Do not modify the sibling ButterflyLens repository.
