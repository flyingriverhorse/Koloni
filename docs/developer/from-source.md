# Run from source

KOLONİ always runs from its source folder; [Install](../getting-started/install.md) covers that.

## Live reload for the page (Windows)

```powershell
./scripts/dev.ps1
```

It starts the backend with `KOLONI_DEV=1` and `KOLONI_OPEN_BROWSER=0`, and Vite's dev server on port
5173. Open the link the backend prints, with the port changed to 5173. `KOLONI_DEV=1` lets the backend
accept the page from port 5173. Stopping the script stops the backend too.

Vite sends `/api` to `127.0.0.1:8790`, so run the dev backend on the default port.

## After changing an API shape

```powershell
cd frontend
npm run generate:api
```

This writes `frontend/src/api/generated.ts` from the backend's schema. The full check fails while the
committed file is stale.

## Build this guide

```powershell
uv pip install -e ".[docs]"
zensical build      # the site in runtime/site
zensical serve      # or watch it at http://127.0.0.1:8000
```

`.github/workflows/docs.yml` builds the guide, checks it, and pushes it to the `gh-pages` branch under
`manual/`, beside the site's root files in `pages/`, when started by hand, and on each push to `main`
that changes the guide once the repository variable `PAGES_ENABLED` is `true`. Pages must be switched
on once in the repository's Settings → Pages: **Deploy from a branch**, `gh-pages`, `/ (root)`
(`.github/CI.md` has the custom domain and DNS steps).
