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

The **Update Arrests** workflow runs every day at 01:00 UTC, commits the refreshed arrest data to `main`, and republishes the Arrests page. To refresh it locally:

```bash
python3 scripts/update_arrests.py
python3 build.py
```

## MemeFleet Statistics

`scripts/update_memefleet_stats.py` retrieves historical W-space kills for The Wormhole Police alliance from July 2020 onward, then keeps kills from completed Sunday 1–3 PM `America/New_York` fleet windows. Each report includes the maximum participant count, unique systems protected, arrests, and total case value. Weeks with no recorded value are omitted. Once a history exists, normal updates fetch only the current and previous months and merge them into the stored dataset; pass `--full` to rebuild the entire history.

The **Update MemeFleet Stats** workflow runs Sundays at 23:00 UTC—at least three hours after the fleet ends in both standard and daylight time—commits the refreshed history to `main`, and republishes `MemeFleet.html`. It can also be run manually from GitHub Actions.

```bash
python3 scripts/update_memefleet_stats.py
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
