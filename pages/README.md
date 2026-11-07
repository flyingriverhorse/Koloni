# pages

The root of https://koloni.skyulf.com, published by `.github/workflows/docs.yml` to the
`gh-pages` branch. Everything here but this README is copied as it is; the guide is built from
`docs/` and added as `manual/` (not kept here).

| File | What |
|---|---|
| `index.html` | The landing page: one HTML file with its CSS and script inline, links into `manual/` |
| `assets/` | Its pictures, the two videos (the tour, two teams at work), the logo and the fonts (OFL, licence in `assets/fonts/OFL.txt`) |
| `CNAME` | The custom domain; without it each publish would drop the domain from Settings → Pages |
| `robots.txt` | Lets every crawler in; names both sitemaps |
| `sitemap.xml` | The root and `manual/` (Zensical writes `manual/sitemap.xml` with every page) |
| `.nojekyll` | Tells Pages not to run Jekyll, so folders starting with `_` are served |

The share card `assets/og.jpg` is drawn from `scripts/og-image.html`; after changing it run `node scripts/og-image.mjs` from the repo root.
