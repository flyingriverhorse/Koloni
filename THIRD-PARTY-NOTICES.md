# Third-party notices

This file lists the third-party software and assets that KOLONİ ships or runs for the user, with each one's licence, its copyright lines and the licence texts. KOLONİ's own licence, AGPL-3.0-or-later, is in [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

Generated on 26 November 2026 by `scripts/notices.py` from the installed versions: `frontend/node_modules` and the backend `.venv` (Windows, Python 3.12). Licence texts and copyright lines are copied from the licence files in the installed packages; the declared licence is the `license` of the package's own `package.json`, or the `License-Expression` / `License` / classifier of its `METADATA`. To make it again, after a dependency changes and before a release: `.venv\Scripts\python.exe scripts\notices.py` (or `.venv/bin/python scripts/notices.py`).

- **Frontend (bundled)**: the `dependencies` of `frontend/package.json` and everything they bring in at run time, from `frontend/package-lock.json`. This is a superset of the bundle: a few Node-only parts are listed although the browser build does not use them (for example `@antfu/install-pkg`, `package-manager-detector`, `tinyexec`, `import-meta-resolve`, and d3-dsv's command-line `commander`, `iconv-lite`, `safer-buffer`, `rw`). Type-only packages (`@types/*`, `csstype`) and the dev tools are not listed, except `vite` and `rolldown`: the build puts their small runtime helpers (the module-preload helper, `rolldown-runtime-*.js`) into the bundle. `elkjs` is not shipped (see Check).
- **Backend (Python)**: the `[project] dependencies` of `pyproject.toml` (with `uvicorn[standard]`) and what they require on this machine, from each package's `Requires-Dist`. The dev extra (`pytest`, `ruff`, `ty`, ...) is not listed.
- A package that appears twice is installed in two versions; each is listed.
- Each licence text is printed once, under **Licence texts**, without its copyright lines; each package names the text it uses and shows its own copyright lines.

Counts: Frontend (bundled) 189, Fonts 2, Backend (Python) 30, Assets in the repository 3.

## Frontend (bundled)

### @antfu/install-pkg 2.1.0

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) 2021 Anthony Fu <https://github.com/antfu>
```

### @braintree/sanitize-url 7.1.2

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) 2017 Braintree
```

### @chevrotain/cst-dts-gen 13.2.0

- Licence: `Apache-2.0` (package.json)
- Apache-2.0: no NOTICE file in the package.

Licence file `LICENSE.txt`: text [L2](#l2).

_No copyright line in the licence file._

### @chevrotain/gast 13.2.0

- Licence: `Apache-2.0` (package.json)
- Apache-2.0: no NOTICE file in the package.

Licence file `LICENSE.txt`: text [L2](#l2).

_No copyright line in the licence file._

### @chevrotain/regexp-to-ast 13.2.0

- Licence: `Apache-2.0` (package.json)
- Apache-2.0: no NOTICE file in the package.

Licence file `LICENSE.txt`: text [L2](#l2).

_No copyright line in the licence file._

### @chevrotain/types 13.2.0

- Licence: `Apache-2.0` (package.json)
- Apache-2.0: no NOTICE file in the package.

Licence file `LICENSE.txt`: text [L2](#l2).

_No copyright line in the licence file._

### @chevrotain/utils 13.2.0

- Licence: `Apache-2.0` (package.json)
- Apache-2.0: no NOTICE file in the package.

Licence file `LICENSE.txt`: text [L2](#l2).

_No copyright line in the licence file._

### @iconify/types 2.0.0

- Licence: `MIT` (package.json)

Licence file `license.txt`: text [L1](#l1).

```text
Copyright (c) 2021 - 2022 Vjacheslav Trushkin / Iconify OÜ
```

### @iconify/utils 3.1.7

- Licence: `MIT` (package.json)

Licence file `license.txt`: text [L1](#l1).

```text
Copyright (c) 2021-PRESENT Vjacheslav Trushkin
```

### @mermaid-js/parser 2.0.1

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L3](#l3).

```text
Copyright (c) 2023 Yokozuna59
```

### @phosphor-icons/react 2.1.10

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) 2020 Phosphor Icons
```

### @ungap/structured-clone 1.4.0

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L4](#l4).

```text
Copyright (c) 2021, Andrea Giammarchi, @WebReflection
```

### @upsetjs/venn.js 2.0.0

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) 2013 Ben Frederickson
Copyright (c) 2021 Samuel Gratzl
```

### @xyflow/react 12.12.0

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) 2019-2025 webkid GmbH
```

### @xyflow/system 0.0.83

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) 2019-2025 webkid GmbH
```

### bail 2.0.2

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2015 Titus Wormer <tituswormer@gmail.com>
```

### ccount 2.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2015 Titus Wormer <tituswormer@gmail.com>
```

### character-entities 2.0.2

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2015 Titus Wormer <tituswormer@gmail.com>
```

### character-entities-html4 2.1.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2015 Titus Wormer <tituswormer@gmail.com>
```

### character-entities-legacy 3.0.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2015 Titus Wormer <tituswormer@gmail.com>
```

### character-reference-invalid 2.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2015 Titus Wormer <tituswormer@gmail.com>
```

### chevrotain 13.2.0

- Licence: `Apache-2.0` (package.json)
- Apache-2.0: no NOTICE file in the package.

Licence file `LICENSE.txt`: text [L2](#l2).

_No copyright line in the licence file._

### classcat 5.0.5

- Licence: `MIT` (package.json)

Licence file `LICENSE.md`: text [L6](#l6).

```text
Copyright © Jorge Bucaran <<https://jorgebucaran.com>>
```

### comma-separated-tokens 2.0.3

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2016 Titus Wormer <tituswormer@gmail.com>
```

### commander 7.2.0

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L5](#l5).

```text
Copyright (c) 2011 TJ Holowaychuk <tj@vision-media.ca>
```

### commander 15.0.0

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L5](#l5).

```text
Copyright (c) 2011 TJ Holowaychuk <tj@vision-media.ca>
```

### cose-base 1.0.3

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) 2019 - present, iVis@Bilkent.
```

### cose-base 2.2.0

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) 2019 - present, iVis@Bilkent.
```

### cytoscape 3.34.4

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L7](#l7).

```text
Copyright (c) 2016-2026, The Cytoscape Consortium.
```

Licence file `license-update.mjs`: text [L8](#l8).

_No copyright line in the licence file._

### cytoscape-cose-bilkent 4.1.0

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L7](#l7).

```text
Copyright (c) 2016-2018, The Cytoscape Consortium.
```

### cytoscape-fcose 2.2.0

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L7](#l7).

```text
Copyright (c) 2018 - present, iVis-at-Bilkent.
```

### d3 7.9.0

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2010-2023 Mike Bostock
```

### d3-array 2.12.1

- Licence: `BSD-3-Clause` (package.json)

Licence file `LICENSE`: text [L10](#l10).

```text
Copyright 2010-2020 Mike Bostock
```

### d3-array 3.2.4

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2010-2023 Mike Bostock
```

### d3-axis 3.0.0

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2010-2021 Mike Bostock
```

### d3-brush 3.0.0

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2010-2021 Mike Bostock
```

### d3-chord 3.0.1

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2010-2021 Mike Bostock
```

### d3-color 3.1.0

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2010-2022 Mike Bostock
```

### d3-contour 4.0.2

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2012-2023 Mike Bostock
```

### d3-delaunay 6.0.4

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2018-2021 Observable, Inc.
Copyright 2021 Mapbox
```

### d3-dispatch 3.0.1

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2010-2021 Mike Bostock
```

### d3-drag 3.0.0

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2010-2021 Mike Bostock
```

### d3-dsv 3.0.1

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2013-2021 Mike Bostock
```

### d3-ease 3.0.1

- Licence: `BSD-3-Clause` (package.json)

Licence file `LICENSE`: text [L10](#l10).

```text
Copyright 2010-2021 Mike Bostock
Copyright 2001 Robert Penner
```

### d3-fetch 3.0.1

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2016-2021 Mike Bostock
```

### d3-force 3.0.0

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2010-2021 Mike Bostock
```

### d3-format 3.1.2

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2010-2026 Mike Bostock
```

### d3-geo 3.1.1

- Licence: `ISC` (package.json)
- `package.json` says ISC; `LICENSE` is ISC and also MIT, for code from Charles Karney (`Copyright 2008-2012 Charles Karney`).

Licence file `LICENSE`: text [L11](#l11).

```text
Copyright 2010-2024 Mike Bostock
Copyright 2008-2012 Charles Karney
```

### d3-hierarchy 3.1.2

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2010-2021 Mike Bostock
```

### d3-interpolate 3.0.1

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2010-2021 Mike Bostock
```

### d3-path 1.0.9

- Licence: `BSD-3-Clause` (package.json)

Licence file `LICENSE`: text [L10](#l10).

```text
Copyright 2015-2016 Mike Bostock
```

### d3-path 3.1.0

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2015-2022 Mike Bostock
```

### d3-polygon 3.0.1

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2010-2021 Mike Bostock
```

### d3-quadtree 3.0.1

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2010-2021 Mike Bostock
```

### d3-random 3.0.1

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2010-2021 Mike Bostock
```

### d3-sankey 0.12.3

- Licence: `BSD-3-Clause` (package.json)

Licence file `LICENSE`: text [L10](#l10).

```text
Copyright 2015, Mike Bostock
```

### d3-scale 4.0.2

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2010-2021 Mike Bostock
```

### d3-scale-chromatic 3.1.0

- Licence: `ISC` (package.json)
- `package.json` says ISC; `LICENSE` is ISC and also an "Apache-Style Software License for ColorBrewer software and ColorBrewer Color Schemes" under Apache-2.0.

Licence file `LICENSE`: text [L12](#l12).

```text
Copyright 2010-2024 Mike Bostock
Copyright 2002 Cynthia Brewer, Mark Harrower, and The Pennsylvania State University
```

### d3-selection 3.0.0

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2010-2021 Mike Bostock
```

### d3-shape 1.3.7

- Licence: `BSD-3-Clause` (package.json)

Licence file `LICENSE`: text [L10](#l10).

```text
Copyright 2010-2015 Mike Bostock
```

### d3-shape 3.2.0

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2010-2022 Mike Bostock
```

### d3-time 3.1.0

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2010-2022 Mike Bostock
```

### d3-time-format 4.1.0

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2010-2021 Mike Bostock
```

### d3-timer 3.0.1

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2010-2021 Mike Bostock
```

### d3-transition 3.0.1

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2010-2021 Mike Bostock
```

### d3-zoom 3.0.0

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2010-2021 Mike Bostock
```

### dagre-d3-es 7.0.14

- Licence: `MIT` (package.json)

Licence file `LICENSE.md`: text [L13](#l13).

```text
Copyright (c) 2022-2024 Thibaut Lassalle, David Newell, Alois Klink, Sidharth Vinod and dagre-es contributors
```

### dayjs 1.11.23

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) 2018-present, iamkun
```

### debug 4.4.3

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L5](#l5).

```text
Copyright (c) 2014-2017 TJ Holowaychuk <tj@vision-media.ca>
Copyright (c) 2018-2021 Josh Junon
```

### decode-named-character-reference 1.3.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### delaunator 5.1.0

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L4](#l4).

```text
Copyright (c) 2026, Mapbox
```

### dequal 2.0.3

- Licence: `MIT` (package.json)

Licence file `license`: text [L3](#l3).

```text
Copyright (c) Luke Edwards <luke.edwards05@gmail.com> (lukeed.com)
```

### devlop 1.1.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2023 Titus Wormer <tituswormer@gmail.com>
```

### dompurify 3.4.17

- Licence: `(MPL-2.0 OR Apache-2.0)` (package.json)
- Apache-2.0: no NOTICE file in the package.
- MPL-2.0 **or** Apache-2.0: the package carries both texts (`LICENSE` is Apache-2.0, `LICENSE-MPL` is MPL-2.0), so a permissive option exists.

Licence file `LICENSE`: text [L2](#l2).

_No copyright line in the licence file._

Licence file `LICENSE-MPL`: text [L14](#l14).

_No copyright line in the licence file._

### es-toolkit 1.52.0

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) 2024 Viva Republica, Inc.
```

Licence file `NOTICE`: text [L15](#l15).

```text
Copyright OpenJS Foundation and other contributors <https://openjsf.org/>
```

### escape-string-regexp 5.0.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L1](#l1).

```text
Copyright (c) Sindre Sorhus <sindresorhus@gmail.com> (https://sindresorhus.com)
```

### estree-util-is-identifier-name 3.0.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2020 Titus Wormer <tituswormer@gmail.com>
```

### extend 3.0.2

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L3](#l3).

```text
Copyright (c) 2014 Stefan Thomas
```

### hachure-fill 0.5.2

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) 2023 Preet Shihn
```

### hast-util-to-jsx-runtime 2.3.6

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### hast-util-whitespace 3.0.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2016 Titus Wormer <tituswormer@gmail.com>
```

### highlight.js 11.12.0

- Licence: `BSD-3-Clause` (package.json)

Licence file `LICENSE`: text [L16](#l16).

```text
Copyright (c) 2006, Ivan Sagalaev.
```

### html-url-attributes 3.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L17](#l17).

```text
Copyright (c) Titus Wormer
```

### iconv-lite 0.6.3

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L18](#l18).

```text
Copyright (c) 2011 Alexander Shtuchkin
```

### import-meta-resolve 4.2.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L19](#l19).

```text
Copyright (c) Titus Wormer <mailto:tituswormer@gmail.com>
Copyright Node.js contributors. All rights reserved.
Copyright Joyent, Inc. and other Node contributors. All rights reserved.
```

### inline-style-parser 0.2.7

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L5](#l5).

```text
Copyright (c) 2012 TJ Holowaychuk <tj@vision-media.ca>
```

### internmap 1.0.1

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2021 Mike Bostock
```

### internmap 2.0.3

- Licence: `ISC` (package.json)

Licence file `LICENSE`: text [L9](#l9).

```text
Copyright 2021 Mike Bostock
```

### is-alphabetical 2.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2016 Titus Wormer <tituswormer@gmail.com>
```

### is-alphanumerical 2.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2016 Titus Wormer <tituswormer@gmail.com>
```

### is-decimal 2.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2016 Titus Wormer <tituswormer@gmail.com>
```

### is-hexadecimal 2.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2016 Titus Wormer <tituswormer@gmail.com>
```

### is-plain-obj 4.1.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L1](#l1).

```text
Copyright (c) Sindre Sorhus <sindresorhus@gmail.com> (https://sindresorhus.com)
```

### katex 0.18.10

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L3](#l3).

```text
Copyright (c) 2013-2020 Khan Academy and other contributors
```

### khroma 2.1.0

- Licence: none (package.json)
- Its `package.json` names no licence; its licence file `license` is MIT.

Licence file `license`: text [L3](#l3).

```text
Copyright (c) 2019-present Fabio Spampinato, Andrew Maney
```

### layout-base 1.0.2

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) 2019 iVis@Bilkent
```

### layout-base 2.0.1

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) 2019 iVis@Bilkent
```

### lodash-es 4.18.1

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L20](#l20).

```text
Copyright OpenJS Foundation and other contributors <https://openjsf.org/>
```

### longest-streak 3.1.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2015 Titus Wormer <mailto:tituswormer@gmail.com>
```

### markdown-table 3.0.4

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### marked 16.4.2

- Licence: `MIT` (package.json)
- `package.json` says MIT; `LICENSE.md` is MIT and also BSD-3-Clause, for the original Markdown (`Copyright © 2004, John Gruber`).

Licence file `LICENSE.md`: text [L21](#l21).

```text
Copyright (c) 2018+, MarkedJS (https://github.com/markedjs/)
Copyright (c) 2011-2018, Christopher Jeffrey (https://github.com/chjj/)
Copyright © 2004, John Gruber
```

### mdast-util-find-and-replace 3.0.3

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### mdast-util-from-markdown 2.1.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### mdast-util-gfm 3.1.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### mdast-util-gfm-autolink-literal 2.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2020 Titus Wormer <tituswormer@gmail.com>
```

### mdast-util-gfm-footnote 2.1.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### mdast-util-gfm-strikethrough 2.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### mdast-util-gfm-table 2.0.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2020 Titus Wormer <tituswormer@gmail.com>
```

### mdast-util-gfm-task-list-item 2.0.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2020 Titus Wormer <tituswormer@gmail.com>
```

### mdast-util-mdx-expression 2.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2020 Titus Wormer <tituswormer@gmail.com>
```

### mdast-util-mdx-jsx 3.2.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2020 Titus Wormer <tituswormer@gmail.com>
```

### mdast-util-mdxjs-esm 2.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2020 Titus Wormer <tituswormer@gmail.com>
```

### mdast-util-phrasing 4.1.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2017 Titus Wormer <tituswormer@gmail.com>
Copyright (c) 2017 Victor Felder <victor@draft.li>
```

### mdast-util-to-hast 13.2.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2016 Titus Wormer <tituswormer@gmail.com>
```

### mdast-util-to-markdown 2.2.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### mdast-util-to-string 4.0.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2015 Titus Wormer <tituswormer@gmail.com>
```

### mermaid 12.2.0

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L3](#l3).

```text
Copyright (c) 2014 - 2022 Knut Sveidqvist
```

### micromark 4.0.3

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### micromark-core-commonmark 2.0.4

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### micromark-extension-gfm 3.0.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2020 Titus Wormer <tituswormer@gmail.com>
```

### micromark-extension-gfm-autolink-literal 2.1.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2020 Titus Wormer <tituswormer@gmail.com>
```

### micromark-extension-gfm-footnote 2.1.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2021 Titus Wormer <tituswormer@gmail.com>
```

### micromark-extension-gfm-strikethrough 2.1.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2020 Titus Wormer <tituswormer@gmail.com>
```

### micromark-extension-gfm-table 2.1.2

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### micromark-extension-gfm-tagfilter 2.0.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2020 Titus Wormer <tituswormer@gmail.com>
```

### micromark-extension-gfm-task-list-item 2.1.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2020 Titus Wormer <tituswormer@gmail.com>
```

### micromark-factory-destination 2.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### micromark-factory-label 2.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### micromark-factory-space 2.1.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### micromark-factory-title 2.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### micromark-factory-whitespace 2.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### micromark-util-character 2.1.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### micromark-util-chunked 2.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### micromark-util-classify-character 2.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### micromark-util-combine-extensions 2.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### micromark-util-decode-numeric-character-reference 2.0.2

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### micromark-util-decode-string 2.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### micromark-util-edit-map 1.0.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### micromark-util-encode 2.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### micromark-util-html-tag-name 2.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### micromark-util-normalize-identifier 2.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### micromark-util-resolve-all 2.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### micromark-util-sanitize-uri 2.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### micromark-util-subtokenize 2.1.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### micromark-util-symbol 2.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### micromark-util-types 2.0.3

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### ms 2.1.3

- Licence: `MIT` (package.json)

Licence file `license.md`: text [L3](#l3).

```text
Copyright (c) 2020 Vercel, Inc.
```

### package-manager-detector 1.9.0

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) 2020-PRESENT Anthony Fu <https://github.com/antfu>
```

### parse-entities 4.0.2

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <mailto:tituswormer@gmail.com>
```

### path-data-parser 0.1.0

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) 2020 Preet Shihn
```

### points-on-curve 0.2.0

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) 2020 Preet Shihn
```

### points-on-path 0.2.1

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) 2020 Preet
```

### property-information 7.2.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <mailto:tituswormer@gmail.com>
```

### react 19.3.0

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) Meta Platforms, Inc. and affiliates.
```

### react-dom 19.3.0

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) Meta Platforms, Inc. and affiliates.
```

### react-markdown 10.1.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L3](#l3).

```text
Copyright (c) Espen Hovlandsdal
```

### remark-gfm 4.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### remark-parse 11.0.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L17](#l17).

```text
Copyright (c) 2014 Titus Wormer <tituswormer@gmail.com>
```

### remark-rehype 11.1.2

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### remark-stringify 11.0.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L17](#l17).

```text
Copyright (c) 2014 Titus Wormer <tituswormer@gmail.com>
```

### robust-predicates 3.0.3

- Licence: `Unlicense` (package.json)

Licence file `LICENSE`: text [L22](#l22).

_No copyright line in the licence file._

### rolldown 1.2.19

- Licence: `MIT` (package.json)
- In the bundle: the `rolldown-runtime-*.js` helper.

Licence file `LICENSE`: text [L23](#l23).

```text
Copyright (c) 2024-present VoidZero Inc. & Contributors
```

### roughjs 4.6.6

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) 2019 Preet Shihn
```

### rw 1.3.3

- Licence: `BSD-3-Clause` (package.json)

Licence file `LICENSE`: text [L24](#l24).

```text
Copyright (c) 2014-2016, Michael Bostock
```

### safer-buffer 2.1.2

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) 2018 Nikita Skovoroda <chalkerx@gmail.com>
```

### scheduler 0.28.0

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) Meta Platforms, Inc. and affiliates.
```

### space-separated-tokens 2.0.2

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2016 Titus Wormer <tituswormer@gmail.com>
```

### stringify-entities 4.0.4

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2015 Titus Wormer <mailto:tituswormer@gmail.com>
```

### style-to-js 1.1.21

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L3](#l3).

```text
Copyright (c) 2020 Menglin "Mark" Xu <mark@remarkablemark.org>
```

### style-to-object 1.0.14

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L3](#l3).

```text
Copyright (c) 2017 Menglin "Mark" Xu <mark@remarkablemark.org>
```

### stylis 4.4.0

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) 2016-present Sultan Tarimo
```

### tinyexec 1.3.1

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) 2024 Tinylibs
```

### trim-lines 3.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2015 Titus Wormer <mailto:tituswormer@gmail.com>
```

### trough 2.2.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L17](#l17).

```text
Copyright (c) 2016 Titus Wormer <tituswormer@gmail.com>
```

### ts-dedent 2.3.0

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) 2018 Tamino Martinius
```

### unified 11.0.5

- Licence: `MIT` (package.json)

Licence file `license`: text [L17](#l17).

```text
Copyright (c) 2015 Titus Wormer <tituswormer@gmail.com>
```

### unist-util-is 6.0.1

- Licence: `MIT` (package.json)

Licence file `license`: text [L25](#l25).

```text
Copyright (c) 2015 Titus Wormer <tituswormer@gmail.com>
```

### unist-util-position 5.0.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2015 Titus Wormer <tituswormer@gmail.com>
```

### unist-util-stringify-position 4.0.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2016 Titus Wormer <tituswormer@gmail.com>
```

### unist-util-visit 5.1.0

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2015 Titus Wormer <tituswormer@gmail.com>
```

### unist-util-visit-parents 6.0.2

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2016 Titus Wormer <tituswormer@gmail.com>
```

### use-sync-external-store 1.7.0

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) Meta Platforms, Inc. and affiliates.
```

### uuid 14.0.3

- Licence: `MIT` (package.json)

Licence file `LICENSE.md`: text [L3](#l3).

```text
Copyright (c) 2010-2020 Robert Kieffer and other contributors
```

### vfile 6.0.3

- Licence: `MIT` (package.json)

Licence file `license`: text [L17](#l17).

```text
Copyright (c) 2015 Titus Wormer <tituswormer@gmail.com>
```

### vfile-message 4.0.3

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) Titus Wormer <tituswormer@gmail.com>
```

### vite 8.3.8

- Licence: `MIT` (package.json)
- In the bundle: the module-preload helper. Its `LICENSE.md` is cut to the first section, "Vite core license"; the rest lists its Node build's own dependencies.

Licence file `LICENSE.md (its first section)`: text [L26](#l26).

```text
Copyright (c) 2019-present, VoidZero Inc. and Vite contributors
```

### zustand 4.5.7

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) 2019 Paul Henschel
```

### zustand 5.0.15

- Licence: `MIT` (package.json)

Licence file `LICENSE`: text [L1](#l1).

```text
Copyright (c) 2019 Paul Henschel
```

### zwitch 2.0.4

- Licence: `MIT` (package.json)

Licence file `license`: text [L5](#l5).

```text
Copyright (c) 2016 Titus Wormer <tituswormer@gmail.com>
```

## Fonts

IBM Plex Sans (400, 500, 600) and IBM Plex Mono (400, 500) are shipped as the `.woff` / `.woff2` files of the `@fontsource` packages: `frontend/src/main.tsx` imports their CSS and the build copies the fonts into `dist/assets`. Nothing is loaded from a font service. The SIL Open Font License asks that its text goes with the fonts.

### @fontsource/ibm-plex-mono 5.3.0

- Licence: `OFL-1.1` (package.json)

Licence file `LICENSE`: text [L27](#l27).

```text
Copyright 2017 IBM Corp. All rights reserved. IBMPlexMono-ThinItalic.ttf: Copyright 2017 IBM Corp. All rights reserved. IBMPlexMono-ExtraLight.ttf: Copyright 2017 IBM Corp. All rights reserved. IBMPlexMono-ExtraLightItalic.ttf: Copyright 2017 IBM Corp. All rights reserved. IBMPlexMono-Light.ttf: Copyright 2017 IBM Corp. All rights reserved. IBMPlexMono-LightItalic.ttf: Copyright 2017 IBM Corp. All rights reserved. IBMPlexMono-Regular.ttf: Copyright 2017 IBM Corp. All rights reserved. IBMPlexMono-Italic.ttf: Copyright 2017 IBM Corp. All rights reserved. IBMPlexMono-Medium.ttf: Copyright 2017 IBM Corp. All rights reserved. IBMPlexMono-MediumItalic.ttf: Copyright 2017 IBM Corp. All rights reserved. IBMPlexMono-SemiBold.ttf: Copyright 2017 IBM Corp. All rights reserved. IBMPlexMono-SemiBoldItalic.ttf: Copyright 2017 IBM Corp. All rights reserved. IBMPlexMono-Bold.ttf: Copyright 2017 IBM Corp. All rights reserved. IBMPlexMono-BoldItalic.ttf: Copyright 2017 IBM Corp. All rights reserved.
```

### @fontsource/ibm-plex-sans 5.3.0

- Licence: `OFL-1.1` (package.json)

Licence file `LICENSE`: text [L27](#l27).

```text
Copyright 2019 IBM Corp. All rights reserved. IBMPlexSans-Italic[wdth,wght].ttf: Copyright 2019 IBM Corp. All rights reserved.
```

## Backend (Python)

### alembic 1.20.0

- Licence: `MIT` (METADATA License-Expression)

Licence file `licenses/LICENSE`: text [L18](#l18).

```text
Copyright 2009-2026 Michael Bayer.
```

### annotated-doc 0.0.5

- Licence: `MIT` (METADATA License-Expression)

Licence file `licenses/LICENSE`: text [L3](#l3).

```text
Copyright (c) 2025 Sebastián Ramírez
```

### annotated-types 0.8.0

- Licence: `MIT` (METADATA License-Expression)

Licence file `licenses/LICENSE`: text [L3](#l3).

```text
Copyright (c) 2022 the contributors
```

### anyio 4.14.2

- Licence: `MIT` (METADATA License-Expression)

Licence file `licenses/LICENSE`: text [L3](#l3).

```text
Copyright (c) 2018 Alex Grönholm
```

### certifi 2026.7.22

- Licence: `MPL-2.0` (METADATA License)
- MPL-2.0 is its only licence; the metadata and the licence file agree. MPL-2.0 is a file-level copyleft licence.

Licence file `licenses/LICENSE`: text [L28](#l28).

_No copyright line in the licence file._

### click 8.5.0

- Licence: `BSD-3-Clause` (METADATA License-Expression)

Licence file `licenses/LICENSE.txt`: text [L29](#l29).

```text
Copyright 2014 Pallets
```

### fastapi 0.141.1

- Licence: `MIT` (METADATA License-Expression)

Licence file `licenses/LICENSE`: text [L3](#l3).

```text
Copyright (c) 2018 Sebastián Ramírez
```

### greenlet 3.5.6

- Licence: `MIT AND PSF-2.0` (METADATA License-Expression)

Licence file `licenses/LICENSE`: text [L30](#l30).

```text
Copyright (c) Armin Rigo, Christian Tismer and contributors
```

Licence file `licenses/LICENSE.PSF`: text [L31](#l31).

_No copyright line in the licence file._

### h11 0.16.0

- Licence: `MIT` (METADATA License)

Licence file `licenses/LICENSE.txt`: text [L3](#l3).

```text
Copyright (c) 2016 Nathaniel J. Smith <njs@pobox.com> and other contributors
```

### httpcore 1.0.9

- Licence: `BSD-3-Clause` (METADATA License-Expression)

Licence file `licenses/LICENSE.md`: text [L32](#l32).

```text
Copyright © 2020, [Encode OSS Ltd](https://www.encode.io/).
```

### httpcore2 2.13.0

- Licence: `BSD-3-Clause` (METADATA License-Expression)

Licence file `licenses/LICENSE.md`: text [L32](#l32).

```text
Copyright © 2026 to present Pydantic Services Inc. and individual contributors.
Copyright © 2020, [Encode OSS Ltd](https://www.encode.io/).
```

### httptools 0.8.0

- Licence: `MIT` (METADATA License-Expression)

Licence file `licenses/LICENSE`: text [L33](#l33).

```text
Copyright (c) 2015 MagicStack Inc.  http://magic.io
```

Licence file `licenses/vendor/http-parser/LICENSE-MIT`: text [L18](#l18).

```text
Copyright Joyent, Inc. and other Node contributors.
```

Licence file `licenses/vendor/llhttp/LICENSE`: text [L1](#l1).

```text
Copyright © 2018 Fedor Indutny
```

### httpx 0.28.1

- Licence: `BSD-3-Clause` (METADATA License)

Licence file `licenses/LICENSE.md`: text [L32](#l32).

```text
Copyright © 2019, [Encode OSS Ltd](https://www.encode.io/).
```

### httpx2 2.13.0

- Licence: `BSD-3-Clause` (METADATA License-Expression)

Licence file `licenses/LICENSE.md`: text [L32](#l32).

```text
Copyright © 2026 to present Pydantic Services Inc. and individual contributors.
Copyright © 2019, [Encode OSS Ltd](https://www.encode.io/).
```

### idna 3.20

- Licence: `BSD-3-Clause` (METADATA License-Expression)

Licence file `licenses/LICENSE.md`: text [L34](#l34).

```text
Copyright (c) 2013-2026, Kim Davies and contributors.
```

### Mako 1.4.1

- Licence: `MIT` (METADATA License-Expression)

Licence file `licenses/LICENSE`: text [L18](#l18).

```text
Copyright 2006-2026 the Mako authors and contributors <see AUTHORS file>.
```

### MarkupSafe 3.0.3

- Licence: `BSD-3-Clause` (METADATA License-Expression)

Licence file `licenses/LICENSE.txt`: text [L29](#l29).

```text
Copyright 2010 Pallets
```

### pydantic 2.14.1

- Licence: `MIT` (METADATA License-Expression)

Licence file `licenses/LICENSE`: text [L3](#l3).

```text
Copyright (c) 2017 to present Pydantic Services Inc. and individual contributors.
```

### pydantic_core 2.50.1

- Licence: `MIT` (METADATA License-Expression)

Licence file `licenses/LICENSE`: text [L3](#l3).

```text
Copyright (c) 2022 Samuel Colvin
```

Rust crates compiled into the wheel, from its CycloneDX SBOM `sboms/pydantic-core.cyclonedx.json` (99; name, version, licence; the SBOM may also count build-only crates; their licence texts are not in the wheel):

```text
ahash 0.8.12  MIT OR Apache-2.0
aho-corasick 1.1.3  Unlicense OR MIT
autocfg 1.3.0  Apache-2.0 OR MIT
base64 0.23.1  MIT OR Apache-2.0
bitflags 2.9.1  MIT OR Apache-2.0
bitvec 1.0.1  MIT
bumpalo 3.19.0  MIT OR Apache-2.0
cfg-if 1.0.0  MIT OR Apache-2.0
displaydoc 0.2.5  MIT OR Apache-2.0
enum_dispatch 0.3.13  MIT OR Apache-2.0
foldhash 0.2.0  Zlib
form_urlencoded 1.2.2  MIT OR Apache-2.0
funty 2.0.0  MIT
getrandom 0.3.3  MIT OR Apache-2.0
hashbrown 0.17.1  MIT OR Apache-2.0
heck 0.5.0  MIT OR Apache-2.0
hex 0.4.3  MIT OR Apache-2.0
icu_collections 1.5.0  Unicode-3.0
icu_locid 1.5.0  Unicode-3.0
icu_locid_transform 1.5.0  Unicode-3.0
icu_locid_transform_data 1.5.0  Unicode-3.0
icu_normalizer 1.5.0  Unicode-3.0
icu_normalizer_data 1.5.0  Unicode-3.0
icu_properties 1.5.1  Unicode-3.0
icu_properties_data 1.5.0  Unicode-3.0
icu_provider 1.5.0  Unicode-3.0
icu_provider_macros 1.5.0  Unicode-3.0
idna 1.1.0  MIT OR Apache-2.0
idna_adapter 1.2.0  Apache-2.0 OR MIT
itoa 1.0.11  MIT OR Apache-2.0
jiter 0.16.0  MIT
js-sys 0.3.77  MIT OR Apache-2.0
lexical-parse-float 1.0.5  MIT OR Apache-2.0
lexical-parse-integer 1.0.5  MIT OR Apache-2.0
lexical-util 1.0.6  MIT OR Apache-2.0
libc 0.2.185  MIT OR Apache-2.0
litemap 0.7.3  Unicode-3.0
log 0.4.27  MIT OR Apache-2.0
lru 0.18.5  MIT
memchr 2.7.4  Unlicense OR MIT
num-bigint 0.4.6  MIT OR Apache-2.0
num-integer 0.1.46  MIT OR Apache-2.0
num-traits 0.2.19  MIT OR Apache-2.0
once_cell 1.21.3  MIT OR Apache-2.0
percent-encoding 2.3.2  MIT OR Apache-2.0
portable-atomic 1.6.0  Apache-2.0 OR MIT
proc-macro2 1.0.107  MIT OR Apache-2.0
pyo3 0.29.2  MIT OR Apache-2.0
pyo3-build-config 0.29.2  MIT OR Apache-2.0
pyo3-ffi 0.29.2  MIT OR Apache-2.0
pyo3-macros 0.29.2  MIT OR Apache-2.0
pyo3-macros-backend 0.29.2  MIT OR Apache-2.0
quote 1.0.44  MIT OR Apache-2.0
r-efi 5.2.0  MIT OR Apache-2.0 OR LGPL-2.1-or-later
radium 0.7.0  MIT
regex 1.13.1  MIT OR Apache-2.0
regex-automata 0.4.18  MIT OR Apache-2.0
regex-syntax 0.8.11  MIT OR Apache-2.0
serde 1.0.229  MIT OR Apache-2.0
serde_core 1.0.229  MIT OR Apache-2.0
serde_derive 1.0.229  MIT OR Apache-2.0
serde_json 1.0.151  MIT OR Apache-2.0
smallvec 1.16.2  MIT OR Apache-2.0
speedate 0.17.0  MIT
stable_deref_trait 1.2.0  MIT OR Apache-2.0
static_assertions 1.1.0  MIT OR Apache-2.0
strum 0.27.2  MIT
strum_macros 0.27.2  MIT
syn 2.0.82  MIT OR Apache-2.0
syn 3.0.6  MIT OR Apache-2.0
synstructure 0.13.1  MIT
tap 1.0.1  MIT
target-lexicon 0.13.4  Apache-2.0 WITH LLVM-exception
tinystr 0.7.6  Unicode-3.0
unicode-ident 1.0.12  (MIT OR Apache-2.0) AND Unicode-DFS-2016
url 2.5.8  MIT OR Apache-2.0
utf16_iter 1.0.5  Apache-2.0 OR MIT
utf8_iter 1.0.4  Apache-2.0 OR MIT
uuid 1.23.4  Apache-2.0 OR MIT
version_check 0.9.5  MIT OR Apache-2.0
wasi 0.14.2+wasi-0.2.4  Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT
wasm-bindgen 0.2.100  MIT OR Apache-2.0
wasm-bindgen-backend 0.2.100  MIT OR Apache-2.0
wasm-bindgen-macro 0.2.100  MIT OR Apache-2.0
wasm-bindgen-macro-support 0.2.100  MIT OR Apache-2.0
wasm-bindgen-shared 0.2.100  MIT OR Apache-2.0
wit-bindgen-rt 0.39.0  Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT
write16 1.0.0  Apache-2.0 OR MIT
writeable 0.5.5  Unicode-3.0
wyz 0.5.1  MIT
yoke 0.7.4  Unicode-3.0
yoke-derive 0.7.4  Unicode-3.0
zerocopy 0.8.25  BSD-2-Clause OR Apache-2.0 OR MIT
zerocopy-derive 0.8.25  BSD-2-Clause OR Apache-2.0 OR MIT
zerofrom 0.1.4  Unicode-3.0
zerofrom-derive 0.1.4  Unicode-3.0
zerovec 0.10.4  Unicode-3.0
zerovec-derive 0.10.3  Unicode-3.0
zmij 1.0.6  MIT
```

### pypdf 6.21.4

- Licence: `BSD-3-Clause` (METADATA License-Expression)

Licence file `licenses/LICENSE`: text [L35](#l35).

```text
Copyright (c) 2006-2008, Mathieu Fenniak
Some contributions copyright (c) 2007, Ashish Kulkarni <kulkarni.ashish@gmail.com>
Some contributions copyright (c) 2014, Steve Witham <switham_github@mac-guyver.com>
```

### python-dotenv 1.2.4

- Licence: `BSD-3-Clause` (METADATA License)

Licence file `licenses/LICENSE`: text [L36](#l36).

```text
Copyright (c) 2014, Saurabh Kumar (python-dotenv), 2013, Ted Tieken (django-dotenv-rw), 2013, Jacob Kaplan-Moss (django-dotenv)
```

### PyYAML 6.0.3

- Licence: `MIT` (METADATA License)

Licence file `licenses/LICENSE`: text [L18](#l18).

```text
Copyright (c) 2017-2021 Ingy döt Net
Copyright (c) 2006-2016 Kirill Simonov
```

### SQLAlchemy 2.0.52

- Licence: `MIT` (METADATA License)

Licence file `licenses/LICENSE`: text [L18](#l18).

```text
Copyright 2005-2026 SQLAlchemy authors and contributors <see AUTHORS file>.
```

### starlette 1.6.0

- Licence: `BSD-3-Clause` (METADATA License-Expression)

Licence file `licenses/LICENSE.md`: text [L32](#l32).

```text
Copyright © 2018, [Encode OSS Ltd](https://www.encode.io/).
```

### truststore 0.10.4

- Licence: `MIT` (METADATA License-Expression)

Licence file `licenses/LICENSE`: text [L3](#l3).

```text
Copyright (c) 2022 Seth Michael Larson
```

### typing-inspection 0.4.4

- Licence: `MIT` (METADATA License-Expression)

Licence file `licenses/LICENSE`: text [L1](#l1).

```text
Copyright (c) Pydantic Services Inc. 2025 to present
```

### typing_extensions 4.16.0

- Licence: `PSF-2.0` (METADATA License-Expression)

Licence file `licenses/LICENSE`: text [L37](#l37).

```text
Copyright (c) 1991 - 1995, Stichting Mathematisch Centrum Amsterdam,
```

### uvicorn 0.53.0

- Licence: `BSD-3-Clause` (METADATA License-Expression)

Licence file `licenses/LICENSE.md`: text [L32](#l32).

```text
Copyright © 2017-present, [Encode OSS Ltd](https://www.encode.io/).
```

### watchfiles 1.2.0

- Licence: `MIT` (METADATA License)

Licence file `licenses/LICENSE`: text [L3](#l3).

```text
Copyright (c) 2017 to present Samuel Colvin
```

Rust crates compiled into the wheel, from its CycloneDX SBOM `sboms/watchfiles_rust_notify.cyclonedx.json` (28; name, version, licence; the SBOM may also count build-only crates; their licence texts are not in the wheel):

```text
cc 1.0.96  MIT OR Apache-2.0
cfg-if 1.0.0  MIT OR Apache-2.0
crossbeam-channel 0.5.15  MIT OR Apache-2.0
crossbeam-utils 0.8.19  MIT OR Apache-2.0
filetime 0.2.24  MIT OR Apache-2.0
heck 0.5.0  MIT OR Apache-2.0
libc 0.2.169  MIT OR Apache-2.0
log 0.4.22  MIT OR Apache-2.0
notify 8.0.0  CC0-1.0
notify-types 2.0.0  MIT OR Apache-2.0
once_cell 1.21.3  MIT OR Apache-2.0
proc-macro2 1.0.81  MIT OR Apache-2.0
pyo3 0.28.3  MIT OR Apache-2.0
pyo3-build-config 0.28.3  MIT OR Apache-2.0
pyo3-ffi 0.28.3  MIT OR Apache-2.0
pyo3-macros 0.28.3  MIT OR Apache-2.0
pyo3-macros-backend 0.28.3  MIT OR Apache-2.0
python3-dll-a 0.2.14  MIT
quote 1.0.45  MIT OR Apache-2.0
same-file 1.0.6  Unlicense OR MIT
syn 2.0.60  MIT OR Apache-2.0
target-lexicon 0.13.5  Apache-2.0 WITH LLVM-exception
unicode-ident 1.0.12  (MIT OR Apache-2.0) AND Unicode-DFS-2016
walkdir 2.5.0  Unlicense OR MIT
winapi-util 0.1.9  Unlicense OR MIT
windows-sys 0.59.0  MIT OR Apache-2.0
windows-targets 0.52.6  MIT OR Apache-2.0
windows_x86_64_msvc 0.52.6  MIT OR Apache-2.0
```

### websockets 17.1

- Licence: `BSD-3-Clause` (METADATA License-Expression)

Licence file `licenses/LICENSE`: text [L38](#l38).

```text
Copyright (c) Aymeric Augustin and contributors
```

## Assets in the repository

### KOLONİ bee logo

- Licence: `the user's own work` (frontend/public/brand/README.md)
- `frontend/public/brand/` (koloni-ari.webm, koloni_ari_vektor.png, koloni_ari_vektor.svg) is KOLONİ's bee, the user's own work; `frontend/public/favicon.svg`, `apple-touch-icon.png` and `icon-512.png` are made from it.

### models.dev data trimmed copy

- Licence: `MIT` (app/models_dev.LICENSE)
- `app/models_dev.json` is a trimmed copy of the models.dev data (github.com/anomalyco/models.dev) that KOLONİ ships.

Licence file `app/models_dev.LICENSE`: text [L1](#l1).

```text
Copyright (c) 2025 models.dev
```

### draw.io viewer (viewer-static.min.js) 32.6.9

- Licence: `Apache-2.0` (frontend/public/drawio/LICENSE)
- Apache-2.0: no NOTICE file in the package.
- `frontend/public/drawio/viewer-static.min.js` is the draw.io static viewer (github.com/jgraph/drawio, v32.6.9), unchanged; KOLONİ's own `koloni.js` beside it keeps it from every address of its own. It draws `.drawio` files in the Workspace and for the agents' `diagram_image`.

Licence file `frontend/public/drawio/LICENSE`: text [L2](#l2).

_No copyright line in the licence file._

## Licence texts

### L1

Used by 35 (declared: MIT): @antfu/install-pkg 2.1.0, @braintree/sanitize-url 7.1.2, @iconify/types 2.0.0, @iconify/utils 3.1.7, @phosphor-icons/react 2.1.10, @upsetjs/venn.js 2.0.0, @xyflow/react 12.12.0, @xyflow/system 0.0.83, cose-base 1.0.3, cose-base 2.2.0, dayjs 1.11.23, es-toolkit 1.52.0, escape-string-regexp 5.0.0, hachure-fill 0.5.2, httptools 0.8.0, is-plain-obj 4.1.0, layout-base 1.0.2, layout-base 2.0.1, models.dev data trimmed copy, package-manager-detector 1.9.0, path-data-parser 0.1.0, points-on-curve 0.2.0, points-on-path 0.2.1, react 19.3.0, react-dom 19.3.0, roughjs 4.6.6, safer-buffer 2.1.2, scheduler 0.28.0, stylis 4.4.0, tinyexec 1.3.1, ts-dedent 2.3.0, typing-inspection 0.4.4, use-sync-external-store 1.7.0, zustand 4.5.7, zustand 5.0.15.

```text
MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### L2

Used by 8 (declared: (MPL-2.0 OR Apache-2.0), Apache-2.0): @chevrotain/cst-dts-gen 13.2.0, @chevrotain/gast 13.2.0, @chevrotain/regexp-to-ast 13.2.0, @chevrotain/types 13.2.0, @chevrotain/utils 13.2.0, chevrotain 13.2.0, dompurify 3.4.17, draw.io viewer (viewer-static.min.js) 32.6.9.

```text
Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

   TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION

   1. Definitions.

      "License" shall mean the terms and conditions for use, reproduction,
      and distribution as defined by Sections 1 through 9 of this document.

      "Licensor" shall mean the copyright owner or entity authorized by
      the copyright owner that is granting the License.

      "Legal Entity" shall mean the union of the acting entity and all
      other entities that control, are controlled by, or are under common
      control with that entity. For the purposes of this definition,
      "control" means (i) the power, direct or indirect, to cause the
      direction or management of such entity, whether by contract or
      otherwise, or (ii) ownership of fifty percent (50%) or more of the
      outstanding shares, or (iii) beneficial ownership of such entity.

      "You" (or "Your") shall mean an individual or Legal Entity
      exercising permissions granted by this License.

      "Source" form shall mean the preferred form for making modifications,
      including but not limited to software source code, documentation
      source, and configuration files.

      "Object" form shall mean any form resulting from mechanical
      transformation or translation of a Source form, including but
      not limited to compiled object code, generated documentation,
      and conversions to other media types.

      "Work" shall mean the work of authorship, whether in Source or
      Object form, made available under the License, as indicated by a
      copyright notice that is included in or attached to the work
      (an example is provided in the Appendix below).

      "Derivative Works" shall mean any work, whether in Source or Object
      form, that is based on (or derived from) the Work and for which the
      editorial revisions, annotations, elaborations, or other modifications
      represent, as a whole, an original work of authorship. For the purposes
      of this License, Derivative Works shall not include works that remain
      separable from, or merely link (or bind by name) to the interfaces of,
      the Work and Derivative Works thereof.

      "Contribution" shall mean any work of authorship, including
      the original version of the Work and any modifications or additions
      to that Work or Derivative Works thereof, that is intentionally
      submitted to Licensor for inclusion in the Work by the copyright owner
      or by an individual or Legal Entity authorized to submit on behalf of
      the copyright owner. For the purposes of this definition, "submitted"
      means any form of electronic, verbal, or written communication sent
      to the Licensor or its representatives, including but not limited to
      communication on electronic mailing lists, source code control systems,
      and issue tracking systems that are managed by, or on behalf of, the
      Licensor for the purpose of discussing and improving the Work, but
      excluding communication that is conspicuously marked or otherwise
      designated in writing by the copyright owner as "Not a Contribution."

      "Contributor" shall mean Licensor and any individual or Legal Entity
      on behalf of whom a Contribution has been received by Licensor and
      subsequently incorporated within the Work.

   2. Grant of Copyright License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      copyright license to reproduce, prepare Derivative Works of,
      publicly display, publicly perform, sublicense, and distribute the
      Work and such Derivative Works in Source or Object form.

   3. Grant of Patent License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      (except as stated in this section) patent license to make, have made,
      use, offer to sell, sell, import, and otherwise transfer the Work,
      where such license applies only to those patent claims licensable
      by such Contributor that are necessarily infringed by their
      Contribution(s) alone or by combination of their Contribution(s)
      with the Work to which such Contribution(s) was submitted. If You
      institute patent litigation against any entity (including a
      cross-claim or counterclaim in a lawsuit) alleging that the Work
      or a Contribution incorporated within the Work constitutes direct
      or contributory patent infringement, then any patent licenses
      granted to You under this License for that Work shall terminate
      as of the date such litigation is filed.

   4. Redistribution. You may reproduce and distribute copies of the
      Work or Derivative Works thereof in any medium, with or without
      modifications, and in Source or Object form, provided that You
      meet the following conditions:

      (a) You must give any other recipients of the Work or
          Derivative Works a copy of this License; and

      (b) You must cause any modified files to carry prominent notices
          stating that You changed the files; and

      (c) You must retain, in the Source form of any Derivative Works
          that You distribute, all copyright, patent, trademark, and
          attribution notices from the Source form of the Work,
          excluding those notices that do not pertain to any part of
          the Derivative Works; and

      (d) If the Work includes a "NOTICE" text file as part of its
          distribution, then any Derivative Works that You distribute must
          include a readable copy of the attribution notices contained
          within such NOTICE file, excluding those notices that do not
          pertain to any part of the Derivative Works, in at least one
          of the following places: within a NOTICE text file distributed
          as part of the Derivative Works; within the Source form or
          documentation, if provided along with the Derivative Works; or,
          within a display generated by the Derivative Works, if and
          wherever such third-party notices normally appear. The contents
          of the NOTICE file are for informational purposes only and
          do not modify the License. You may add Your own attribution
          notices within Derivative Works that You distribute, alongside
          or as an addendum to the NOTICE text from the Work, provided
          that such additional attribution notices cannot be construed
          as modifying the License.

      You may add Your own copyright statement to Your modifications and
      may provide additional or different license terms and conditions
      for use, reproduction, or distribution of Your modifications, or
      for any such Derivative Works as a whole, provided Your use,
      reproduction, and distribution of the Work otherwise complies with
      the conditions stated in this License.

   5. Submission of Contributions. Unless You explicitly state otherwise,
      any Contribution intentionally submitted for inclusion in the Work
      by You to the Licensor shall be under the terms and conditions of
      this License, without any additional terms or conditions.
      Notwithstanding the above, nothing herein shall supersede or modify
      the terms of any separate license agreement you may have executed
      with Licensor regarding such Contributions.

   6. Trademarks. This License does not grant permission to use the trade
      names, trademarks, service marks, or product names of the Licensor,
      except as required for reasonable and customary use in describing the
      origin of the Work and reproducing the content of the NOTICE file.

   7. Disclaimer of Warranty. Unless required by applicable law or
      agreed to in writing, Licensor provides the Work (and each
      Contributor provides its Contributions) on an "AS IS" BASIS,
      WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
      implied, including, without limitation, any warranties or conditions
      of TITLE, NON-INFRINGEMENT, MERCHANTABILITY, or FITNESS FOR A
      PARTICULAR PURPOSE. You are solely responsible for determining the
      appropriateness of using or redistributing the Work and assume any
      risks associated with Your exercise of permissions under this License.

   8. Limitation of Liability. In no event and under no legal theory,
      whether in tort (including negligence), contract, or otherwise,
      unless required by applicable law (such as deliberate and grossly
      negligent acts) or agreed to in writing, shall any Contributor be
      liable to You for damages, including any direct, indirect, special,
      incidental, or consequential damages of any character arising as a
      result of this License or out of the use or inability to use the
      Work (including but not limited to damages for loss of goodwill,
      work stoppage, computer failure or malfunction, or any and all
      other commercial damages or losses), even if such Contributor
      has been advised of the possibility of such damages.

   9. Accepting Warranty or Additional Liability. While redistributing
      the Work or Derivative Works thereof, You may choose to offer,
      and charge a fee for, acceptance of support, warranty, indemnity,
      or other liability obligations and/or rights consistent with this
      License. However, in accepting such obligations, You may act only
      on Your own behalf and on Your sole responsibility, not on behalf
      of any other Contributor, and only if You agree to indemnify,
      defend, and hold each Contributor harmless for any liability
      incurred by, or claims asserted against, such Contributor by reason
      of your accepting any such warranty or additional liability.

   END OF TERMS AND CONDITIONS

   APPENDIX: How to apply the Apache License to your work.

      To apply the Apache License to your work, attach the following
      boilerplate notice, with the fields enclosed by brackets "[]"
      replaced with your own identifying information. (Don't include
      the brackets!)  The text should be enclosed in the appropriate
      comment syntax for the file format. We also recommend that a
      file or class name and description of purpose be included on the
      same "printed page" as the copyright notice for easier
      identification within third-party archives.

   Copyright [yyyy] [name of copyright owner]

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
```

### L3

Used by 20 (declared: MIT, none declared): @mermaid-js/parser 2.0.1, annotated-doc 0.0.5, annotated-types 0.8.0, anyio 4.14.2, dequal 2.0.3, extend 3.0.2, fastapi 0.141.1, h11 0.16.0, katex 0.18.10, khroma 2.1.0, mermaid 12.2.0, ms 2.1.3, pydantic 2.14.1, pydantic_core 2.50.1, react-markdown 10.1.0, style-to-js 1.1.21, style-to-object 1.0.14, truststore 0.10.4, uuid 14.0.3, watchfiles 1.2.0.

```text
The MIT License (MIT)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### L4

Used by 2 (declared: ISC): @ungap/structured-clone 1.4.0, delaunator 5.1.0.

```text
ISC License

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE
OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
PERFORMANCE OF THIS SOFTWARE.
```

### L5

Used by 79 (declared: MIT): bail 2.0.2, ccount 2.0.1, character-entities 2.0.2, character-entities-html4 2.1.0, character-entities-legacy 3.0.0, character-reference-invalid 2.0.1, comma-separated-tokens 2.0.3, commander 15.0.0, commander 7.2.0, debug 4.4.3, decode-named-character-reference 1.3.0, devlop 1.1.0, estree-util-is-identifier-name 3.0.0, hast-util-to-jsx-runtime 2.3.6, hast-util-whitespace 3.0.0, inline-style-parser 0.2.7, is-alphabetical 2.0.1, is-alphanumerical 2.0.1, is-decimal 2.0.1, is-hexadecimal 2.0.1, longest-streak 3.1.0, markdown-table 3.0.4, mdast-util-find-and-replace 3.0.3, mdast-util-from-markdown 2.1.0, mdast-util-gfm 3.1.0, mdast-util-gfm-autolink-literal 2.0.1, mdast-util-gfm-footnote 2.1.0, mdast-util-gfm-strikethrough 2.0.1, mdast-util-gfm-table 2.0.0, mdast-util-gfm-task-list-item 2.0.0, mdast-util-mdx-expression 2.0.1, mdast-util-mdx-jsx 3.2.0, mdast-util-mdxjs-esm 2.0.1, mdast-util-phrasing 4.1.0, mdast-util-to-hast 13.2.1, mdast-util-to-markdown 2.2.0, mdast-util-to-string 4.0.0, micromark 4.0.3, micromark-core-commonmark 2.0.4, micromark-extension-gfm 3.0.0, micromark-extension-gfm-autolink-literal 2.1.0, micromark-extension-gfm-footnote 2.1.0, micromark-extension-gfm-strikethrough 2.1.0, micromark-extension-gfm-table 2.1.2, micromark-extension-gfm-tagfilter 2.0.0, micromark-extension-gfm-task-list-item 2.1.0, micromark-factory-destination 2.0.1, micromark-factory-label 2.0.1, micromark-factory-space 2.1.0, micromark-factory-title 2.0.1, micromark-factory-whitespace 2.0.1, micromark-util-character 2.1.1, micromark-util-chunked 2.0.1, micromark-util-classify-character 2.0.1, micromark-util-combine-extensions 2.0.1, micromark-util-decode-numeric-character-reference 2.0.2, micromark-util-decode-string 2.0.1, micromark-util-edit-map 1.0.0, micromark-util-encode 2.0.1, micromark-util-html-tag-name 2.0.1, micromark-util-normalize-identifier 2.0.1, micromark-util-resolve-all 2.0.1, micromark-util-sanitize-uri 2.0.1, micromark-util-subtokenize 2.1.0, micromark-util-symbol 2.0.1, micromark-util-types 2.0.3, parse-entities 4.0.2, property-information 7.2.0, remark-gfm 4.0.1, remark-rehype 11.1.2, space-separated-tokens 2.0.2, stringify-entities 4.0.4, trim-lines 3.0.1, unist-util-position 5.0.0, unist-util-stringify-position 4.0.0, unist-util-visit 5.1.0, unist-util-visit-parents 6.0.2, vfile-message 4.0.3, zwitch 2.0.4.

```text
(The MIT License)

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
'Software'), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED 'AS IS', WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

### L6

Used by 1 (declared: MIT): classcat 5.0.5.

```text
Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the 'Software'), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED 'AS IS', WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

### L7

Used by 3 (declared: MIT): cytoscape 3.34.4, cytoscape-cose-bilkent 4.1.0, cytoscape-fcose 2.2.0.

```text
Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the “Software”), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### L8

Used by 1 (declared: MIT): cytoscape 3.34.4.

```text
import fs from 'fs';
import path from 'path';

import { fileURLToPath } from 'url';
import { dirname } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const year = (new Date()).getFullYear();

const license = `Copyright (c) 2016-${year}, The Cytoscape Consortium.

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the “Software”), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.`;

fs.writeFileSync(path.join(__dirname, 'LICENSE'), license);
```

### L9

Used by 30 (declared: ISC): d3 7.9.0, d3-array 3.2.4, d3-axis 3.0.0, d3-brush 3.0.0, d3-chord 3.0.1, d3-color 3.1.0, d3-contour 4.0.2, d3-delaunay 6.0.4, d3-dispatch 3.0.1, d3-drag 3.0.0, d3-dsv 3.0.1, d3-fetch 3.0.1, d3-force 3.0.0, d3-format 3.1.2, d3-hierarchy 3.1.2, d3-interpolate 3.0.1, d3-path 3.1.0, d3-polygon 3.0.1, d3-quadtree 3.0.1, d3-random 3.0.1, d3-scale 4.0.2, d3-selection 3.0.0, d3-shape 3.2.0, d3-time 3.1.0, d3-time-format 4.1.0, d3-timer 3.0.1, d3-transition 3.0.1, d3-zoom 3.0.0, internmap 1.0.1, internmap 2.0.3.

```text
Permission to use, copy, modify, and/or distribute this software for any purpose
with or without fee is hereby granted, provided that the above copyright notice
and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND
FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS
OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER
TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF
THIS SOFTWARE.
```

### L10

Used by 5 (declared: BSD-3-Clause): d3-array 2.12.1, d3-ease 3.0.1, d3-path 1.0.9, d3-sankey 0.12.3, d3-shape 1.3.7.

```text
All rights reserved.

Redistribution and use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

* Neither the name of the author nor the names of contributors may be used to
  endorse or promote products derived from this software without specific prior
  written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

### L11

Used by 1 (declared: ISC): d3-geo 3.1.1.

```text
Permission to use, copy, modify, and/or distribute this software for any purpose
with or without fee is hereby granted, provided that the above copyright notice
and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND
FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS
OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER
TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF
THIS SOFTWARE.

This license applies to GeographicLib, versions 1.12 and later.

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

### L12

Used by 1 (declared: ISC): d3-scale-chromatic 3.1.0.

```text
Permission to use, copy, modify, and/or distribute this software for any purpose
with or without fee is hereby granted, provided that the above copyright notice
and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND
FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS
OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER
TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF
THIS SOFTWARE.

Apache-Style Software License for ColorBrewer software and ColorBrewer Color Schemes

Licensed under the Apache License, Version 2.0 (the "License"); you may not use
this file except in compliance with the License. You may obtain a copy of the
License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed
under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.
```

### L13

Used by 1 (declared: MIT): dagre-d3-es 7.0.14.

```text
Original dagre-d3 copyright: Copyright (c) 2013 Chris Pettitt
Original dagre copyright: Copyright (c) 2012-2014 Chris Pettitt
Original graphlib copyright: Copyright (c) 2012-2014 Chris Pettitt

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

### L14

Used by 1 (declared: (MPL-2.0 OR Apache-2.0)): dompurify 3.4.17.

```text
Mozilla Public License Version 2.0
==================================

1. Definitions
--------------

1.1. "Contributor"
    means each individual or legal entity that creates, contributes to
    the creation of, or owns Covered Software.

1.2. "Contributor Version"
    means the combination of the Contributions of others (if any) used
    by a Contributor and that particular Contributor's Contribution.

1.3. "Contribution"
    means Covered Software of a particular Contributor.

1.4. "Covered Software"
    means Source Code Form to which the initial Contributor has attached
    the notice in Exhibit A, the Executable Form of such Source Code
    Form, and Modifications of such Source Code Form, in each case
    including portions thereof.

1.5. "Incompatible With Secondary Licenses"
    means

    (a) that the initial Contributor has attached the notice described
        in Exhibit B to the Covered Software; or

    (b) that the Covered Software was made available under the terms of
        version 1.1 or earlier of the License, but not also under the
        terms of a Secondary License.

1.6. "Executable Form"
    means any form of the work other than Source Code Form.

1.7. "Larger Work"
    means a work that combines Covered Software with other material, in
    a separate file or files, that is not Covered Software.

1.8. "License"
    means this document.

1.9. "Licensable"
    means having the right to grant, to the maximum extent possible,
    whether at the time of the initial grant or subsequently, any and
    all of the rights conveyed by this License.

1.10. "Modifications"
    means any of the following:

    (a) any file in Source Code Form that results from an addition to,
        deletion from, or modification of the contents of Covered
        Software; or

    (b) any new file in Source Code Form that contains any Covered
        Software.

1.11. "Patent Claims" of a Contributor
    means any patent claim(s), including without limitation, method,
    process, and apparatus claims, in any patent Licensable by such
    Contributor that would be infringed, but for the grant of the
    License, by the making, using, selling, offering for sale, having
    made, import, or transfer of either its Contributions or its
    Contributor Version.

1.12. "Secondary License"
    means either the GNU General Public License, Version 2.0, the GNU
    Lesser General Public License, Version 2.1, the GNU Affero General
    Public License, Version 3.0, or any later versions of those
    licenses.

1.13. "Source Code Form"
    means the form of the work preferred for making modifications.

1.14. "You" (or "Your")
    means an individual or a legal entity exercising rights under this
    License. For legal entities, "You" includes any entity that
    controls, is controlled by, or is under common control with You. For
    purposes of this definition, "control" means (a) the power, direct
    or indirect, to cause the direction or management of such entity,
    whether by contract or otherwise, or (b) ownership of more than
    fifty percent (50%) of the outstanding shares or beneficial
    ownership of such entity.

2. License Grants and Conditions
--------------------------------

2.1. Grants

Each Contributor hereby grants You a world-wide, royalty-free,
non-exclusive license:

(a) under intellectual property rights (other than patent or trademark)
    Licensable by such Contributor to use, reproduce, make available,
    modify, display, perform, distribute, and otherwise exploit its
    Contributions, either on an unmodified basis, with Modifications, or
    as part of a Larger Work; and

(b) under Patent Claims of such Contributor to make, use, sell, offer
    for sale, have made, import, and otherwise transfer either its
    Contributions or its Contributor Version.

2.2. Effective Date

The licenses granted in Section 2.1 with respect to any Contribution
become effective for each Contribution on the date the Contributor first
distributes such Contribution.

2.3. Limitations on Grant Scope

The licenses granted in this Section 2 are the only rights granted under
this License. No additional rights or licenses will be implied from the
distribution or licensing of Covered Software under this License.
Notwithstanding Section 2.1(b) above, no patent license is granted by a
Contributor:

(a) for any code that a Contributor has removed from Covered Software;
    or

(b) for infringements caused by: (i) Your and any other third party's
    modifications of Covered Software, or (ii) the combination of its
    Contributions with other software (except as part of its Contributor
    Version); or

(c) under Patent Claims infringed by Covered Software in the absence of
    its Contributions.

This License does not grant any rights in the trademarks, service marks,
or logos of any Contributor (except as may be necessary to comply with
the notice requirements in Section 3.4).

2.4. Subsequent Licenses

No Contributor makes additional grants as a result of Your choice to
distribute the Covered Software under a subsequent version of this
License (see Section 10.2) or under the terms of a Secondary License (if
permitted under the terms of Section 3.3).

2.5. Representation

Each Contributor represents that the Contributor believes its
Contributions are its original creation(s) or it has sufficient rights
to grant the rights to its Contributions conveyed by this License.

2.6. Fair Use

This License is not intended to limit any rights You have under
applicable copyright doctrines of fair use, fair dealing, or other
equivalents.

2.7. Conditions

Sections 3.1, 3.2, 3.3, and 3.4 are conditions of the licenses granted
in Section 2.1.

3. Responsibilities
-------------------

3.1. Distribution of Source Form

All distribution of Covered Software in Source Code Form, including any
Modifications that You create or to which You contribute, must be under
the terms of this License. You must inform recipients that the Source
Code Form of the Covered Software is governed by the terms of this
License, and how they can obtain a copy of this License. You may not
attempt to alter or restrict the recipients' rights in the Source Code
Form.

3.2. Distribution of Executable Form

If You distribute Covered Software in Executable Form then:

(a) such Covered Software must also be made available in Source Code
    Form, as described in Section 3.1, and You must inform recipients of
    the Executable Form how they can obtain a copy of such Source Code
    Form by reasonable means in a timely manner, at a charge no more
    than the cost of distribution to the recipient; and

(b) You may distribute such Executable Form under the terms of this
    License, or sublicense it under different terms, provided that the
    license for the Executable Form does not attempt to limit or alter
    the recipients' rights in the Source Code Form under this License.

3.3. Distribution of a Larger Work

You may create and distribute a Larger Work under terms of Your choice,
provided that You also comply with the requirements of this License for
the Covered Software. If the Larger Work is a combination of Covered
Software with a work governed by one or more Secondary Licenses, and the
Covered Software is not Incompatible With Secondary Licenses, this
License permits You to additionally distribute such Covered Software
under the terms of such Secondary License(s), so that the recipient of
the Larger Work may, at their option, further distribute the Covered
Software under the terms of either this License or such Secondary
License(s).

3.4. Notices

You may not remove or alter the substance of any license notices
(including copyright notices, patent notices, disclaimers of warranty,
or limitations of liability) contained within the Source Code Form of
the Covered Software, except that You may alter any license notices to
the extent required to remedy known factual inaccuracies.

3.5. Application of Additional Terms

You may choose to offer, and to charge a fee for, warranty, support,
indemnity or liability obligations to one or more recipients of Covered
Software. However, You may do so only on Your own behalf, and not on
behalf of any Contributor. You must make it absolutely clear that any
such warranty, support, indemnity, or liability obligation is offered by
You alone, and You hereby agree to indemnify every Contributor for any
liability incurred by such Contributor as a result of warranty, support,
indemnity or liability terms You offer. You may include additional
disclaimers of warranty and limitations of liability specific to any
jurisdiction.

4. Inability to Comply Due to Statute or Regulation
---------------------------------------------------

If it is impossible for You to comply with any of the terms of this
License with respect to some or all of the Covered Software due to
statute, judicial order, or regulation then You must: (a) comply with
the terms of this License to the maximum extent possible; and (b)
describe the limitations and the code they affect. Such description must
be placed in a text file included with all distributions of the Covered
Software under this License. Except to the extent prohibited by statute
or regulation, such description must be sufficiently detailed for a
recipient of ordinary skill to be able to understand it.

5. Termination
--------------

5.1. The rights granted under this License will terminate automatically
if You fail to comply with any of its terms. However, if You become
compliant, then the rights granted under this License from a particular
Contributor are reinstated (a) provisionally, unless and until such
Contributor explicitly and finally terminates Your grants, and (b) on an
ongoing basis, if such Contributor fails to notify You of the
non-compliance by some reasonable means prior to 60 days after You have
come back into compliance. Moreover, Your grants from a particular
Contributor are reinstated on an ongoing basis if such Contributor
notifies You of the non-compliance by some reasonable means, this is the
first time You have received notice of non-compliance with this License
from such Contributor, and You become compliant prior to 30 days after
Your receipt of the notice.

5.2. If You initiate litigation against any entity by asserting a patent
infringement claim (excluding declaratory judgment actions,
counter-claims, and cross-claims) alleging that a Contributor Version
directly or indirectly infringes any patent, then the rights granted to
You by any and all Contributors for the Covered Software under Section
2.1 of this License shall terminate.

5.3. In the event of termination under Sections 5.1 or 5.2 above, all
end user license agreements (excluding distributors and resellers) which
have been validly granted by You or Your distributors under this License
prior to termination shall survive termination.

************************************************************************
*                                                                      *
*  6. Disclaimer of Warranty                                           *
*  -------------------------                                           *
*                                                                      *
*  Covered Software is provided under this License on an "as is"       *
*  basis, without warranty of any kind, either expressed, implied, or  *
*  statutory, including, without limitation, warranties that the       *
*  Covered Software is free of defects, merchantable, fit for a        *
*  particular purpose or non-infringing. The entire risk as to the     *
*  quality and performance of the Covered Software is with You.        *
*  Should any Covered Software prove defective in any respect, You     *
*  (not any Contributor) assume the cost of any necessary servicing,   *
*  repair, or correction. This disclaimer of warranty constitutes an   *
*  essential part of this License. No use of any Covered Software is   *
*  authorized under this License except under this disclaimer.         *
*                                                                      *
************************************************************************

************************************************************************
*                                                                      *
*  7. Limitation of Liability                                          *
*  --------------------------                                          *
*                                                                      *
*  Under no circumstances and under no legal theory, whether tort      *
*  (including negligence), contract, or otherwise, shall any           *
*  Contributor, or anyone who distributes Covered Software as          *
*  permitted above, be liable to You for any direct, indirect,         *
*  special, incidental, or consequential damages of any character      *
*  including, without limitation, damages for lost profits, loss of    *
*  goodwill, work stoppage, computer failure or malfunction, or any    *
*  and all other commercial damages or losses, even if such party      *
*  shall have been informed of the possibility of such damages. This   *
*  limitation of liability shall not apply to liability for death or   *
*  personal injury resulting from such party's negligence to the       *
*  extent applicable law prohibits such limitation. Some               *
*  jurisdictions do not allow the exclusion or limitation of           *
*  incidental or consequential damages, so this exclusion and          *
*  limitation may not apply to You.                                    *
*                                                                      *
************************************************************************

8. Litigation
-------------

Any litigation relating to this License may be brought only in the
courts of a jurisdiction where the defendant maintains its principal
place of business and such litigation shall be governed by laws of that
jurisdiction, without reference to its conflict-of-law provisions.
Nothing in this Section shall prevent a party's ability to bring
cross-claims or counter-claims.

9. Miscellaneous
----------------

This License represents the complete agreement concerning the subject
matter hereof. If any provision of this License is held to be
unenforceable, such provision shall be reformed only to the extent
necessary to make it enforceable. Any law or regulation which provides
that the language of a contract shall be construed against the drafter
shall not be used to construe this License against a Contributor.

10. Versions of the License
---------------------------

10.1. New Versions

Mozilla Foundation is the license steward. Except as provided in Section
10.3, no one other than the license steward has the right to modify or
publish new versions of this License. Each version will be given a
distinguishing version number.

10.2. Effect of New Versions

You may distribute the Covered Software under the terms of the version
of the License under which You originally received the Covered Software,
or under the terms of any subsequent version published by the license
steward.

10.3. Modified Versions

If you create software not governed by this License, and you want to
create a new license for such software, you may create and use a
modified version of this License if you rename the license and remove
any references to the name of the license steward (except to note that
such modified license differs from this License).

10.4. Distributing Source Code Form that is Incompatible With Secondary
Licenses

If You choose to distribute Source Code Form that is Incompatible With
Secondary Licenses under the terms of this version of the License, the
notice described in Exhibit B of this License must be attached.

Exhibit A - Source Code Form License Notice
-------------------------------------------

  This Source Code Form is subject to the terms of the Mozilla Public
  License, v. 2.0. If a copy of the MPL was not distributed with this
  file, You can obtain one at http://mozilla.org/MPL/2.0/.

If it is not possible or desirable to put the notice in a particular
file, then You may include the notice in a location (such as a LICENSE
file in a relevant directory) where a recipient would be likely to look
for such a notice.

You may add additional accurate notices of copyright ownership.

Exhibit B - "Incompatible With Secondary Licenses" Notice
---------------------------------------------------------

  This Source Code Form is "Incompatible With Secondary Licenses", as
  defined by the Mozilla Public License, v. 2.0.
```

### L15

Used by 1 (declared: MIT): es-toolkit 1.52.0.

```text
es-toolkit

Parts of the test suite and compatibility layer in es-toolkit/compat are
derived from Lodash (https://github.com/lodash/lodash).

Lodash copyright notice and MIT permission notice:

Based on Underscore.js, copyright Jeremy Ashkenas,
DocumentCloud and Investigative Reporters & Editors <http://underscorejs.org/>

This software consists of voluntary contributions made by many
individuals. For exact contribution history, see the revision history
available at https://github.com/lodash/lodash

The following license applies to all parts of this software except as
documented below:

====

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

### L16

Used by 1 (declared: BSD-3-Clause): highlight.js 11.12.0.

```text
BSD 3-Clause License

All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

* Neither the name of the copyright holder nor the names of its
  contributors may be used to endorse or promote products derived from
  this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

### L17

Used by 6 (declared: MIT): html-url-attributes 3.0.1, remark-parse 11.0.0, remark-stringify 11.0.0, trough 2.2.0, unified 11.0.5, vfile 6.0.3.

```text
(The MIT License)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

### L18

Used by 6 (declared: MIT): alembic 1.20.0, httptools 0.8.0, iconv-lite 0.6.3, Mako 1.4.1, PyYAML 6.0.3, SQLAlchemy 2.0.52.

```text
Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

### L19

Used by 1 (declared: MIT): import-meta-resolve 4.2.0.

```text
(The MIT License)

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
'Software'), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED 'AS IS', WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

---

This is a derivative work based on:
<https://github.com/nodejs/node>.
Which is licensed:

"""

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to
deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
sell copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
IN THE SOFTWARE.
"""

This license applies to parts of Node.js originating from the
https://github.com/joyent/node repository:

"""
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to
deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
sell copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
IN THE SOFTWARE.
"""
```

### L20

Used by 1 (declared: MIT): lodash-es 4.18.1.

```text
Based on Underscore.js, copyright Jeremy Ashkenas,
DocumentCloud and Investigative Reporters & Editors <http://underscorejs.org/>

This software consists of voluntary contributions made by many
individuals. For exact contribution history, see the revision history
available at https://github.com/lodash/lodash

The following license applies to all parts of this software except as
documented below:

====

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

====

Copyright and related rights for sample code are waived via CC0. Sample
code is defined as all source code displayed within the prose of the
documentation.

CC0: http://creativecommons.org/publicdomain/zero/1.0/

====

Files located in the node_modules and vendor directories are externally
maintained libraries used by this software which have their own
licenses; we recommend you read them, as their terms may differ from the
terms above.
```

### L21

Used by 1 (declared: MIT): marked 16.4.2.

```text
# License information

## Contribution License Agreement

If you contribute code to this project, you are implicitly allowing your code
to be distributed under the MIT license. You are also implicitly verifying that
all code is your original work. `</legalese>`

## Marked

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

## Markdown

http://daringfireball.net/
All rights reserved.

Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
* Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
* Neither the name “Markdown” nor the names of its contributors may be used to endorse or promote products derived from this software without specific prior written permission.

This software is provided by the copyright holders and contributors “as is” and any express or implied warranties, including, but not limited to, the implied warranties of merchantability and fitness for a particular purpose are disclaimed. In no event shall the copyright owner or contributors be liable for any direct, indirect, incidental, special, exemplary, or consequential damages (including, but not limited to, procurement of substitute goods or services; loss of use, data, or profits; or business interruption) however caused and on any theory of liability, whether in contract, strict liability, or tort (including negligence or otherwise) arising in any way out of the use of this software, even if advised of the possibility of such damage.
```

### L22

Used by 1 (declared: Unlicense): robust-predicates 3.0.3.

```text
This is free and unencumbered software released into the public domain.

Anyone is free to copy, modify, publish, use, compile, sell, or
distribute this software, either in source code form or as a compiled
binary, for any purpose, commercial or non-commercial, and by any
means.

In jurisdictions that recognize copyright laws, the author or authors
of this software dedicate any and all copyright interest in the
software to the public domain. We make this dedication for the benefit
of the public at large and to the detriment of our heirs and
successors. We intend this dedication to be an overt act of
relinquishment in perpetuity of all present and future rights to this
software under copyright law.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS BE LIABLE FOR ANY CLAIM, DAMAGES OR
OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.

For more information, please refer to <http://unlicense.org>
```

### L23

Used by 1 (declared: MIT): rolldown 1.2.19.

```text
MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

end of terms and conditions

The licenses of externally maintained libraries from which parts of the Software is derived are listed [here](https://github.com/rolldown/rolldown/blob/main/THIRD-PARTY-LICENSE).
```

### L24

Used by 1 (declared: BSD-3-Clause): rw 1.3.3.

```text
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

* The name Michael Bostock may not be used to endorse or promote products
  derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL MICHAEL BOSTOCK BE LIABLE FOR ANY DIRECT,
INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY
OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,
EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

### L25

Used by 1 (declared: MIT): unist-util-is 6.0.1.

```text
(The MIT license)

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
'Software'), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED 'AS IS', WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

### L26

Used by 1 (declared: MIT): vite 8.3.8.

```text
# Vite core license
Vite is released under the MIT license:

MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### L27

Used by 2 (declared: OFL-1.1): @fontsource/ibm-plex-mono 5.3.0, @fontsource/ibm-plex-sans 5.3.0.

```text
This Font Software is licensed under the SIL Open Font License, Version 1.1.
This license is copied below, and is also available with a FAQ at:
http://scripts.sil.org/OFL

-----------------------------------------------------------
SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007
-----------------------------------------------------------

PREAMBLE
The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font creation
efforts of academic and linguistic communities, and to provide a free and
open framework in which fonts may be shared and improved in partnership
with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded,
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply
to any document created using the fonts or their derivatives.

DEFINITIONS
"Font Software" refers to the set of files released by the Copyright
Holder(s) under this license and clearly marked as such. This may
include source files, build scripts and documentation.

"Reserved Font Name" refers to any names specified as such after the
copyright statement(s).

"Original Version" refers to the collection of Font Software components as
distributed by the Copyright Holder(s).

"Modified Version" refers to any derivative made by adding to, deleting,
or substituting -- in part or in whole -- any of the components of the
Original Version, by changing formats or by porting the Font Software to a
new environment.

"Author" refers to any designer, engineer, programmer, technical
writer or other person who contributed to the Font Software.

PERMISSION & CONDITIONS
Permission is hereby granted, free of charge, to any person obtaining
a copy of the Font Software, to use, study, copy, merge, embed, modify,
redistribute, and sell modified and unmodified copies of the Font
Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components,
in Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or
in the appropriate machine-readable metadata fields within text or
binary files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless explicit written permission is granted by the corresponding
Copyright Holder. This restriction only applies to the primary font name as
presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any
Modified Version, except to acknowledge the contribution(s) of the
Copyright Holder(s) and the Author(s) or with their explicit written
permission.

5) The Font Software, modified or unmodified, in part or in whole,
must be distributed entirely under this license, and must not be
distributed under any other license. The requirement for fonts to
remain under this license does not apply to any document created
using the Font Software.

TERMINATION
This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER
THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.
```

### L28

Used by 1 (declared: MPL-2.0): certifi 2026.7.22.

```text
This package contains a modified version of ca-bundle.crt:

ca-bundle.crt -- Bundle of CA Root Certificates

This is a bundle of X.509 certificates of public Certificate Authorities
(CA). These were automatically extracted from Mozilla's root certificates
file (certdata.txt).  This file can be found in the mozilla source tree:
https://hg.mozilla.org/mozilla-central/file/tip/security/nss/lib/ckfw/builtins/certdata.txt
It contains the certificates in PEM format and therefore
can be directly used with curl / libcurl / php_curl, or with
an Apache+mod_ssl webserver for SSL client authentication.
Just configure this file as the SSLCACertificateFile.#

***** BEGIN LICENSE BLOCK *****
This Source Code Form is subject to the terms of the Mozilla Public License,
v. 2.0. If a copy of the MPL was not distributed with this file, You can obtain
one at http://mozilla.org/MPL/2.0/.

***** END LICENSE BLOCK *****
@(#) $RCSfile: certdata.txt,v $ $Revision: 1.80 $ $Date: 2011/11/03 15:11:58 $
```

### L29

Used by 2 (declared: BSD-3-Clause): click 8.5.0, MarkupSafe 3.0.3.

```text
Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

1.  Redistributions of source code must retain the above copyright
    notice, this list of conditions and the following disclaimer.

2.  Redistributions in binary form must reproduce the above copyright
    notice, this list of conditions and the following disclaimer in the
    documentation and/or other materials provided with the distribution.

3.  Neither the name of the copyright holder nor the names of its
    contributors may be used to endorse or promote products derived from
    this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED
TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

### L30

Used by 1 (declared: MIT AND PSF-2.0): greenlet 3.5.6.

```text
The following files are derived from Stackless Python and are subject to the
same license as Stackless Python:

	src/greenlet/slp_platformselect.h
	files in src/greenlet/platform/ directory

See LICENSE.PSF and http://www.stackless.com/ for details.

Unless otherwise noted, the files in greenlet have been released under the
following MIT license:

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

### L31

Used by 1 (declared: MIT AND PSF-2.0): greenlet 3.5.6.

```text
PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2
--------------------------------------------

1. This LICENSE AGREEMENT is between the Python Software Foundation
("PSF"), and the Individual or Organization ("Licensee") accessing and
otherwise using this software ("Python") in source or binary form and
its associated documentation.

2. Subject to the terms and conditions of this License Agreement, PSF hereby
grants Licensee a nonexclusive, royalty-free, world-wide license to reproduce,
analyze, test, perform and/or display publicly, prepare derivative works,
distribute, and otherwise use Python alone or in any derivative version,
provided, however, that PSF's License Agreement and PSF's notice of copyright,
i.e., "Copyright (c) 2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008, 2009, 2010,
2011 Python Software Foundation; All Rights Reserved" are retained in Python
alone or in any derivative version prepared by Licensee.

3. In the event Licensee prepares a derivative work that is based on
or incorporates Python or any part thereof, and wants to make
the derivative work available to others as provided herein, then
Licensee hereby agrees to include in any such work a brief summary of
the changes made to Python.

4. PSF is making Python available to Licensee on an "AS IS"
basis.  PSF MAKES NO REPRESENTATIONS OR WARRANTIES, EXPRESS OR
IMPLIED.  BY WAY OF EXAMPLE, BUT NOT LIMITATION, PSF MAKES NO AND
DISCLAIMS ANY REPRESENTATION OR WARRANTY OF MERCHANTABILITY OR FITNESS
FOR ANY PARTICULAR PURPOSE OR THAT THE USE OF PYTHON WILL NOT
INFRINGE ANY THIRD PARTY RIGHTS.

5. PSF SHALL NOT BE LIABLE TO LICENSEE OR ANY OTHER USERS OF PYTHON
FOR ANY INCIDENTAL, SPECIAL, OR CONSEQUENTIAL DAMAGES OR LOSS AS
A RESULT OF MODIFYING, DISTRIBUTING, OR OTHERWISE USING PYTHON,
OR ANY DERIVATIVE THEREOF, EVEN IF ADVISED OF THE POSSIBILITY THEREOF.

6. This License Agreement will automatically terminate upon a material
breach of its terms and conditions.

7. Nothing in this License Agreement shall be deemed to create any
relationship of agency, partnership, or joint venture between PSF and
Licensee.  This License Agreement does not grant permission to use PSF
trademarks or trade name in a trademark sense to endorse or promote
products or services of Licensee, or any third party.

8. By copying, installing or otherwise using Python, Licensee
agrees to be bound by the terms and conditions of this License
Agreement.
```

### L32

Used by 6 (declared: BSD-3-Clause): httpcore 1.0.9, httpcore2 2.13.0, httpx 0.28.1, httpx2 2.13.0, starlette 1.6.0, uvicorn 0.53.0.

```text
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

* Neither the name of the copyright holder nor the names of its
  contributors may be used to endorse or promote products derived from
  this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

### L33

Used by 1 (declared: MIT): httptools 0.8.0.

```text
The MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

### L34

Used by 1 (declared: BSD-3-Clause): idna 3.20.

```text
BSD 3-Clause License

All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

1. Redistributions of source code must retain the above copyright
   notice, this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in the
   documentation and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED
TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

### L35

Used by 1 (declared: BSD-3-Clause): pypdf 6.21.4.

```text
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

* Redistributions of source code must retain the above copyright notice,
this list of conditions and the following disclaimer.
* Redistributions in binary form must reproduce the above copyright notice,
this list of conditions and the following disclaimer in the documentation
and/or other materials provided with the distribution.
* The name of the author may not be used to endorse or promote products
derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
```

### L36

Used by 1 (declared: BSD-3-Clause): python-dotenv 1.2.4.

```text
Redistribution and use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met:

- Redistributions of source code must retain the above copyright notice,
  this list of conditions and the following disclaimer.

- Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

- Neither the name of django-dotenv nor the names of its contributors
  may be used to endorse or promote products derived from this software
  without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

### L37

Used by 1 (declared: PSF-2.0): typing_extensions 4.16.0.

```text
A. HISTORY OF THE SOFTWARE
==========================

Python was created in the early 1990s by Guido van Rossum at Stichting
Mathematisch Centrum (CWI, see https://www.cwi.nl) in the Netherlands
as a successor of a language called ABC.  Guido remains Python's
principal author, although it includes many contributions from others.

In 1995, Guido continued his work on Python at the Corporation for
National Research Initiatives (CNRI, see https://www.cnri.reston.va.us)
in Reston, Virginia where he released several versions of the
software.

In May 2000, Guido and the Python core development team moved to
BeOpen.com to form the BeOpen PythonLabs team.  In October of the same
year, the PythonLabs team moved to Digital Creations, which became
Zope Corporation.  In 2001, the Python Software Foundation (PSF, see
https://www.python.org/psf/) was formed, a non-profit organization
created specifically to own Python-related Intellectual Property.
Zope Corporation was a sponsoring member of the PSF.

All Python releases are Open Source (see https://opensource.org for
the Open Source Definition).  Historically, most, but not all, Python
releases have also been GPL-compatible; the table below summarizes
the various releases.

    Release         Derived     Year        Owner       GPL-
                    from                                compatible? (1)

    0.9.0 thru 1.2              1991-1995   CWI         yes
    1.3 thru 1.5.2  1.2         1995-1999   CNRI        yes
    1.6             1.5.2       2000        CNRI        no
    2.0             1.6         2000        BeOpen.com  no
    1.6.1           1.6         2001        CNRI        yes (2)
    2.1             2.0+1.6.1   2001        PSF         no
    2.0.1           2.0+1.6.1   2001        PSF         yes
    2.1.1           2.1+2.0.1   2001        PSF         yes
    2.1.2           2.1.1       2002        PSF         yes
    2.1.3           2.1.2       2002        PSF         yes
    2.2 and above   2.1.1       2001-now    PSF         yes

Footnotes:

(1) GPL-compatible doesn't mean that we're distributing Python under
    the GPL.  All Python licenses, unlike the GPL, let you distribute
    a modified version without making your changes open source.  The
    GPL-compatible licenses make it possible to combine Python with
    other software that is released under the GPL; the others don't.

(2) According to Richard Stallman, 1.6.1 is not GPL-compatible,
    because its license has a choice of law clause.  According to
    CNRI, however, Stallman's lawyer has told CNRI's lawyer that 1.6.1
    is "not incompatible" with the GPL.

Thanks to the many outside volunteers who have worked under Guido's
direction to make these releases possible.

B. TERMS AND CONDITIONS FOR ACCESSING OR OTHERWISE USING PYTHON
===============================================================

Python software and documentation are licensed under the
Python Software Foundation License Version 2.

Starting with Python 3.8.6, examples, recipes, and other code in
the documentation are dual licensed under the PSF License Version 2
and the Zero-Clause BSD license.

Some software incorporated into Python is under different licenses.
The licenses are listed with code falling under that license.

PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2
--------------------------------------------

1. This LICENSE AGREEMENT is between the Python Software Foundation
("PSF"), and the Individual or Organization ("Licensee") accessing and
otherwise using this software ("Python") in source or binary form and
its associated documentation.

2. Subject to the terms and conditions of this License Agreement, PSF hereby
grants Licensee a nonexclusive, royalty-free, world-wide license to reproduce,
analyze, test, perform and/or display publicly, prepare derivative works,
distribute, and otherwise use Python alone or in any derivative version,
provided, however, that PSF's License Agreement and PSF's notice of copyright,
i.e., "Copyright (c) 2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008, 2009, 2010,
2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023 Python Software Foundation;
All Rights Reserved" are retained in Python alone or in any derivative version
prepared by Licensee.

3. In the event Licensee prepares a derivative work that is based on
or incorporates Python or any part thereof, and wants to make
the derivative work available to others as provided herein, then
Licensee hereby agrees to include in any such work a brief summary of
the changes made to Python.

4. PSF is making Python available to Licensee on an "AS IS"
basis.  PSF MAKES NO REPRESENTATIONS OR WARRANTIES, EXPRESS OR
IMPLIED.  BY WAY OF EXAMPLE, BUT NOT LIMITATION, PSF MAKES NO AND
DISCLAIMS ANY REPRESENTATION OR WARRANTY OF MERCHANTABILITY OR FITNESS
FOR ANY PARTICULAR PURPOSE OR THAT THE USE OF PYTHON WILL NOT
INFRINGE ANY THIRD PARTY RIGHTS.

5. PSF SHALL NOT BE LIABLE TO LICENSEE OR ANY OTHER USERS OF PYTHON
FOR ANY INCIDENTAL, SPECIAL, OR CONSEQUENTIAL DAMAGES OR LOSS AS
A RESULT OF MODIFYING, DISTRIBUTING, OR OTHERWISE USING PYTHON,
OR ANY DERIVATIVE THEREOF, EVEN IF ADVISED OF THE POSSIBILITY THEREOF.

6. This License Agreement will automatically terminate upon a material
breach of its terms and conditions.

7. Nothing in this License Agreement shall be deemed to create any
relationship of agency, partnership, or joint venture between PSF and
Licensee.  This License Agreement does not grant permission to use PSF
trademarks or trade name in a trademark sense to endorse or promote
products or services of Licensee, or any third party.

8. By copying, installing or otherwise using Python, Licensee
agrees to be bound by the terms and conditions of this License
Agreement.

BEOPEN.COM LICENSE AGREEMENT FOR PYTHON 2.0
-------------------------------------------

BEOPEN PYTHON OPEN SOURCE LICENSE AGREEMENT VERSION 1

1. This LICENSE AGREEMENT is between BeOpen.com ("BeOpen"), having an
office at 160 Saratoga Avenue, Santa Clara, CA 95051, and the
Individual or Organization ("Licensee") accessing and otherwise using
this software in source or binary form and its associated
documentation ("the Software").

2. Subject to the terms and conditions of this BeOpen Python License
Agreement, BeOpen hereby grants Licensee a non-exclusive,
royalty-free, world-wide license to reproduce, analyze, test, perform
and/or display publicly, prepare derivative works, distribute, and
otherwise use the Software alone or in any derivative version,
provided, however, that the BeOpen Python License is retained in the
Software, alone or in any derivative version prepared by Licensee.

3. BeOpen is making the Software available to Licensee on an "AS IS"
basis.  BEOPEN MAKES NO REPRESENTATIONS OR WARRANTIES, EXPRESS OR
IMPLIED.  BY WAY OF EXAMPLE, BUT NOT LIMITATION, BEOPEN MAKES NO AND
DISCLAIMS ANY REPRESENTATION OR WARRANTY OF MERCHANTABILITY OR FITNESS
FOR ANY PARTICULAR PURPOSE OR THAT THE USE OF THE SOFTWARE WILL NOT
INFRINGE ANY THIRD PARTY RIGHTS.

4. BEOPEN SHALL NOT BE LIABLE TO LICENSEE OR ANY OTHER USERS OF THE
SOFTWARE FOR ANY INCIDENTAL, SPECIAL, OR CONSEQUENTIAL DAMAGES OR LOSS
AS A RESULT OF USING, MODIFYING OR DISTRIBUTING THE SOFTWARE, OR ANY
DERIVATIVE THEREOF, EVEN IF ADVISED OF THE POSSIBILITY THEREOF.

5. This License Agreement will automatically terminate upon a material
breach of its terms and conditions.

6. This License Agreement shall be governed by and interpreted in all
respects by the law of the State of California, excluding conflict of
law provisions.  Nothing in this License Agreement shall be deemed to
create any relationship of agency, partnership, or joint venture
between BeOpen and Licensee.  This License Agreement does not grant
permission to use BeOpen trademarks or trade names in a trademark
sense to endorse or promote products or services of Licensee, or any
third party.  As an exception, the "BeOpen Python" logos available at
http://www.pythonlabs.com/logos.html may be used according to the
permissions granted on that web page.

7. By copying, installing or otherwise using the software, Licensee
agrees to be bound by the terms and conditions of this License
Agreement.

CNRI LICENSE AGREEMENT FOR PYTHON 1.6.1
---------------------------------------

1. This LICENSE AGREEMENT is between the Corporation for National
Research Initiatives, having an office at 1895 Preston White Drive,
Reston, VA 20191 ("CNRI"), and the Individual or Organization
("Licensee") accessing and otherwise using Python 1.6.1 software in
source or binary form and its associated documentation.

2. Subject to the terms and conditions of this License Agreement, CNRI
hereby grants Licensee a nonexclusive, royalty-free, world-wide
license to reproduce, analyze, test, perform and/or display publicly,
prepare derivative works, distribute, and otherwise use Python 1.6.1
alone or in any derivative version, provided, however, that CNRI's
License Agreement and CNRI's notice of copyright, i.e., "Copyright (c)
1995-2001 Corporation for National Research Initiatives; All Rights
Reserved" are retained in Python 1.6.1 alone or in any derivative
version prepared by Licensee.  Alternately, in lieu of CNRI's License
Agreement, Licensee may substitute the following text (omitting the
quotes): "Python 1.6.1 is made available subject to the terms and
conditions in CNRI's License Agreement.  This Agreement together with
Python 1.6.1 may be located on the internet using the following
unique, persistent identifier (known as a handle): 1895.22/1013.  This
Agreement may also be obtained from a proxy server on the internet
using the following URL: http://hdl.handle.net/1895.22/1013".

3. In the event Licensee prepares a derivative work that is based on
or incorporates Python 1.6.1 or any part thereof, and wants to make
the derivative work available to others as provided herein, then
Licensee hereby agrees to include in any such work a brief summary of
the changes made to Python 1.6.1.

4. CNRI is making Python 1.6.1 available to Licensee on an "AS IS"
basis.  CNRI MAKES NO REPRESENTATIONS OR WARRANTIES, EXPRESS OR
IMPLIED.  BY WAY OF EXAMPLE, BUT NOT LIMITATION, CNRI MAKES NO AND
DISCLAIMS ANY REPRESENTATION OR WARRANTY OF MERCHANTABILITY OR FITNESS
FOR ANY PARTICULAR PURPOSE OR THAT THE USE OF PYTHON 1.6.1 WILL NOT
INFRINGE ANY THIRD PARTY RIGHTS.

5. CNRI SHALL NOT BE LIABLE TO LICENSEE OR ANY OTHER USERS OF PYTHON
1.6.1 FOR ANY INCIDENTAL, SPECIAL, OR CONSEQUENTIAL DAMAGES OR LOSS AS
A RESULT OF MODIFYING, DISTRIBUTING, OR OTHERWISE USING PYTHON 1.6.1,
OR ANY DERIVATIVE THEREOF, EVEN IF ADVISED OF THE POSSIBILITY THEREOF.

6. This License Agreement will automatically terminate upon a material
breach of its terms and conditions.

7. This License Agreement shall be governed by the federal
intellectual property law of the United States, including without
limitation the federal copyright law, and, to the extent such
U.S. federal law does not apply, by the law of the Commonwealth of
Virginia, excluding Virginia's conflict of law provisions.
Notwithstanding the foregoing, with regard to derivative works based
on Python 1.6.1 that incorporate non-separable material that was
previously distributed under the GNU General Public License (GPL), the
law of the Commonwealth of Virginia shall govern this License
Agreement only as to issues arising under or with respect to
Paragraphs 4, 5, and 7 of this License Agreement.  Nothing in this
License Agreement shall be deemed to create any relationship of
agency, partnership, or joint venture between CNRI and Licensee.  This
License Agreement does not grant permission to use CNRI trademarks or
trade name in a trademark sense to endorse or promote products or
services of Licensee, or any third party.

8. By clicking on the "ACCEPT" button where indicated, or by copying,
installing or otherwise using Python 1.6.1, Licensee agrees to be
bound by the terms and conditions of this License Agreement.

        ACCEPT

CWI LICENSE AGREEMENT FOR PYTHON 0.9.0 THROUGH 1.2
--------------------------------------------------

The Netherlands.  All rights reserved.

Permission to use, copy, modify, and distribute this software and its
documentation for any purpose and without fee is hereby granted,
provided that the above copyright notice appear in all copies and that
both that copyright notice and this permission notice appear in
supporting documentation, and that the name of Stichting Mathematisch
Centrum or CWI not be used in advertising or publicity pertaining to
distribution of the software without specific, written prior
permission.

STICHTING MATHEMATISCH CENTRUM DISCLAIMS ALL WARRANTIES WITH REGARD TO
THIS SOFTWARE, INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND
FITNESS, IN NO EVENT SHALL STICHTING MATHEMATISCH CENTRUM BE LIABLE
FOR ANY SPECIAL, INDIRECT OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT
OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

ZERO-CLAUSE BSD LICENSE FOR CODE IN THE PYTHON DOCUMENTATION
----------------------------------------------------------------------

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
PERFORMANCE OF THIS SOFTWARE.
```

### L38

Used by 1 (declared: BSD-3-Clause): websockets 17.1.

```text
Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

    * Redistributions of source code must retain the above copyright notice,
      this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright notice,
      this list of conditions and the following disclaimer in the documentation
      and/or other materials provided with the distribution.
    * Neither the name of the copyright holder nor the names of its contributors
      may be used to endorse or promote products derived from this software
      without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## Check

Facts gathered for the choice of KOLONİ's own licence (AGPL-3.0-or-later, chosen on 6 November 2026).

### Copyleft or unknown licence

- Frontend (bundled): **dompurify**: `(MPL-2.0 OR Apache-2.0)`. MPL-2.0 **or** Apache-2.0: the package carries both texts (`LICENSE` is Apache-2.0, `LICENSE-MPL` is MPL-2.0), so a permissive option exists.
- Frontend (bundled): **khroma**: `no licence declared`. Its `package.json` names no licence; its licence file `license` is MIT.
- Frontend (bundled): **@fontsource/ibm-plex-mono**: `OFL-1.1`.
- Frontend (bundled): **@fontsource/ibm-plex-sans**: `OFL-1.1`.
- Backend (Python): **certifi**: `MPL-2.0`. MPL-2.0 is its only licence; the metadata and the licence file agree. MPL-2.0 is a file-level copyleft licence.
- Backend (Python), Rust crate in pydantic_core's SBOM: **r-efi 5.2.0**: `MIT OR Apache-2.0 OR LGPL-2.1-or-later`. Permissive options exist.
- Not shipped: **elkjs**, `EPL-2.0`, is in mermaid's dependency tree. `frontend/vite.config.ts` replaces it, and mermaid's ELK layout module that alone imports it, with the stub `frontend/src/chat/no-elk.ts`; diagrams are laid out with dagre. It is not listed above.
- Not installed on Windows, so not listed when made there: on Linux and macOS `uvicorn[standard]` also installs **uvloop** (`sys_platform != 'win32'`). Run this script on those platforms before a release there.

### Declared licence differs from the licence file

- **d3-geo**: `package.json` says ISC; `LICENSE` is ISC and also MIT, for code from Charles Karney (`Copyright 2008-2012 Charles Karney`).
- **d3-scale-chromatic**: `package.json` says ISC; `LICENSE` is ISC and also an "Apache-Style Software License for ColorBrewer software and ColorBrewer Color Schemes" under Apache-2.0.
- **khroma**: Its `package.json` names no licence; its licence file `license` is MIT.
- **marked**: `package.json` says MIT; `LICENSE.md` is MIT and also BSD-3-Clause, for the original Markdown (`Copyright © 2004, John Gruber`).
