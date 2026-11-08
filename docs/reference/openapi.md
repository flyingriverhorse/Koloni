# HTTP API

KOLONİ's page talks to KOLONİ through an HTTP API under `/api`, on `127.0.0.1`. The API is made for the
page; it is not a public interface and may change between versions.

## The page key

Every `/api` request must carry the page key, in the `X-KOLONI-Key` header (or `?key=` for event streams
and downloads). Without it the answer is 401: "open KOLONİ from the link in its window". The key is in the
link KOLONİ prints at the start, after `#key=`.

A few doors need no key:

- `GET /api/health`;
- `POST /api/hooks/{key}`: a trigger's webhook, with its own key in the address, from this machine only;
- `POST /api/limits/claude-session`: Claude Code's status line;
- `POST /api/open`: swapping the one-time code for the key;
- the frames that show files and views.

## The schema

KOLONİ does not serve API docs or its OpenAPI schema. To get the schema, run, from KOLONİ's folder:

```powershell
.venv/Scripts/python.exe scripts/export_openapi.py openapi.json
```

It builds the app with a temporary data folder and writes its OpenAPI description. The page's own types
(`frontend/src/api/generated.ts`) are generated from it with `npm run generate:api` in `frontend/`.
