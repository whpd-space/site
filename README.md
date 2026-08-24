# WHPD Website

Static website for The Wormhole Police Department, deployed via GitHub Pages.

## Quick Start

```bash
# Build all pages from templates
python3 build.py

# Test locally (serves from docs/)
python3 server.py

# Auto-rebuild on template changes
python3 watch.py
```

## Structure

```
whpd.space/
├── templates/
│   ├── base.html              # Layout with header/footer
│   └── *.content.html         # Page content (EDIT THESE)
├── docs/                      # Generated site (GitHub Pages)
│   ├── *.html                 # Built pages
│   ├── css/, images/, etc.    # Assets
└── build.py, watch.py         # Build tools
```

## Workflow

1. **Edit** templates in `templates/`
2. **Build** with `python3 build.py`
3. **Test** with `python3 server.py` (optional)
4. **Deploy** - commit and push to GitHub

## Arrests Data

`scripts/update_arrests.py` queries zKillboard for the rolling seven-day W-space kill history of every character in `data/officers.json`. Shared killmails are deduplicated, public names are resolved through EVE ESI, and the result is written to `data/arrests.json` for `build.py` to render.

The deploy workflow refreshes this data and republishes the site every day at 01:00 UTC. To refresh it locally:

```bash
python3 scripts/update_arrests.py
python3 build.py
```

## GitHub Pages Setup

**Repository Settings → Pages:**
- Source: Deploy from a branch
- Branch: `main`
- Folder: `/docs`

Your site will be at `https://USERNAME.github.io/REPO/`

## Making Changes

**Edit content:**
```bash
nano templates/Mission.content.html
python3 build.py
```

**Edit layout (header/footer):**
```bash
nano templates/base.html
python3 build.py  # Rebuilds all pages
```

**Add new page:**
1. Create `templates/newpage.content.html`
2. Add to `PAGES` list in `build.py`
3. Run `python3 build.py`

## License

© YC 127 WHPD | ALL RIGHTS RESERVED
