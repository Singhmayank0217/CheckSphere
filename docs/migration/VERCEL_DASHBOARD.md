# Web dashboard on Vercel: routing

The web dashboard is an Expo Router single-page app (`frontend/app.json`: `"web": { "output": "single" }`). The build
contains one `index.html`; every dashboard URL (`/admin/agents`, `/admin/cases/<id>`, `/supervisor/...`) is resolved in
the browser.

## Why a rewrite is needed
Without a rewrite, Vercel looks for a file at the requested path, finds none and answers `404 NOT_FOUND`
(`X-Vercel-Error: NOT_FOUND`). That is why opening or refreshing a nested dashboard page returned 404 while `/`
worked.

`frontend/vercel.json` sends every path that is not a real file to `/index.html`:

```json
{ "rewrites": [{ "source": "/(.*)", "destination": "/index.html" }] }
```

Vercel serves existing files (the `_expo/static/...` bundles, `favicon.ico`, `assets/...`) before rewrites, so static
assets are not affected.

## Deployment root directory (assumption — confirm in Vercel)
- `vercel.json` is read **only from the Vercel project's Root Directory**.
- This fix assumes the Vercel project's **Root Directory is `frontend`** (where `package.json` and `app.json` are).
  This could not be verified from the repository; check it under Vercel → Project → Settings → Build and Deployment
  → Root Directory.
- If the Root Directory is the repository root instead, move `vercel.json` to the repository root (same content).
- Build output: `npx expo export --platform web` writes to `dist/`.

## Loading screen
`frontend/public/index.html` is the HTML template Expo uses for the single-page web build (`app/+html.tsx` is used
only for static rendering, not for this build). It shows a CheckSphere loader until the JavaScript has started,
instead of a blank white page.

## After deploying, check
- Open and refresh `/admin/agents`, `/admin/cases/<id>` and `/supervisor/agents`: no 404.
- A logged-out visit to a nested page redirects to the sign-in page.
