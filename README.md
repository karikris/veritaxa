# VeriTaxa

VeriTaxa is a minimal, authenticated image-triage interface for recording broad
human labels against remotely hosted candidate images. It is a separate
application from ButterflyLens.

GitHub Pages hosts only the static interface. Private campaigns, image URLs,
source metadata, reviewer authorisation, and append-only reviews live in
Supabase Postgres behind authentication, row-level security, and narrowly
scoped RPC functions. The browser displays an image directly from its source
host with a normal `<img>` element; VeriTaxa does not proxy, mirror, or embed a
source webpage.

Image-level labels describe what is visibly present. They are not bounding
boxes, segmentation masks, detector-ready localisation annotations, or
species-level confirmations.

## Local development

Requirements:

- Node.js 22.12 or later
- npm 9 or later

Create a local environment file from `.env.example`, then run:

```text
npm ci
npm run dev
```

The public browser configuration consists only of a Supabase project URL and a
publishable key. Never use a secret or service-role key in a `VITE_` variable.

## Project status

The application is under initial development. Database setup, reviewer
provisioning, candidate import, review export, and production deployment
instructions are added in their corresponding implementation phases.

## Dependencies

Runtime dependencies are intentionally limited to the Supabase JavaScript
client, which is added with the authenticated data layer. Development
dependencies provide the Vite build, strict TypeScript checking, linting,
formatting, and deterministic DOM tests.

## Licence

VeriTaxa is licensed under the GNU Affero General Public License v3.0. See
[LICENSE](LICENSE).
