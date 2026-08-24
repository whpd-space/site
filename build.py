#!/usr/bin/env python3
"""
Simple template builder for WHPD website.
Generates static pages from templates for GitHub Pages deployment.
Templates are in templates/, output goes to docs/ directory.
"""

import os
import re
import json
import html
from datetime import datetime
from pathlib import Path

# Define source and output directories
TEMPLATE_DIR = Path('templates')
OUTPUT_DIR = Path('docs')
ARRESTS_DATA_FILE = Path('data/arrests.json')

# Template markers
TITLE_MARKER = '{{TITLE}}'
CONTENT_MARKER = '{{CONTENT}}'

# Pages to build (filename, title)
PAGES = [
    ('index.html', 'The Wormhole Police'),
    ('Mission.html', 'The Wormhole Police - Mission'),
    ('AboutUs.html', 'The Wormhole Police - About Us'),
    ('ContactUs.html', 'The Wormhole Police - Contact Us'),
    ('LegalLibrary.html', 'The Wormhole Police - Legal Library'),
    ('Arrests.html', 'The Wormhole Police - Arrests'),
    ('MemeFleet.html', 'The Wormhole Police - MemeFleet'),
    ('MabelMotivation.html', 'The Wormhole Police - Mabel Motivation'),
    ('404.html', 'The Wormhole Police - 404'),
    ('legislation.html', 'The Wormhole Police - Legislation (Redirect)'),
    ('MarkeeDragonRedirect.html', 'The Wormhole Police - Markee Dragon Redirect'),
    ('HighsecBuybackRedirect.html', 'The Wormhole Police - Highsec Buyback Redirect'),
    ('LowsecBuybackRedirect.html', 'The Wormhole Police - Lowsec Buyback Redirect'),
    ('FreeSkillPointsRedirect.html', 'The Wormhole Police - Free Skill Points Redirect'),
]


def format_isk(value):
    """Format an ISK amount for compact display."""
    value = float(value or 0)
    for divisor, suffix in ((1_000_000_000_000, 't'), (1_000_000_000, 'b'), (1_000_000, 'm'), (1_000, 'k')):
        if value >= divisor:
            return f'{value / divisor:.2f}{suffix} ISK'
    return f'{value:,.0f} ISK'


def format_timestamp(value):
    """Format an ISO timestamp in a consistent UTC display."""
    timestamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return f'{timestamp:%b} {timestamp.day}, {timestamp:%Y} at {timestamp:%H:%M} UTC'


def render_arrests_content(data_file=ARRESTS_DATA_FILE):
    """Render the generated arrest JSON into the Arrests page."""
    with open(data_file, 'r', encoding='utf-8') as arrests_file:
        data = json.load(arrests_file)

    escape = lambda value: html.escape(str(value), quote=True)
    summary = data.get('summary', {})
    rankings = [officer for officer in data.get('rankings', []) if int(officer.get('arrests', 0)) >= 5]
    dirtbags = data.get('dirtbags', [])[:25]
    window = data.get('window', {})

    sections = ['<div class="arrests-meta">']
    if window.get('end') and data.get('generated_at'):
        sections.extend([
            f'<span>Rolling seven days ending {escape(format_timestamp(window["end"]))}</span>',
            f'<span>Last refreshed {escape(format_timestamp(data["generated_at"]))}</span>',
        ])
    else:
        sections.append('<span>Awaiting the first GitHub Actions refresh</span>')

    sections.extend([
        '</div>',
        '<section class="arrest-summary" aria-labelledby="arrest-summary-title">',
        '<h2 id="arrest-summary-title">Weekly blotter</h2>',
        '<div class="arrest-stat-grid">',
        f'<div class="arrest-stat"><strong>{int(summary.get("arrests", 0)):,}</strong><span>Arrests</span></div>',
        f'<div class="arrest-stat"><strong>{int(summary.get("suspects", 0)):,}</strong><span>Suspects</span></div>',
        f'<div class="arrest-stat"><strong>{escape(format_isk(summary.get("total_value", 0)))}</strong><span>Property seized</span></div>',
        '</div>',
        '</section>',
        '<section class="arrest-rankings" aria-labelledby="arrest-rankings-title">',
        '<div class="arrest-section-heading">',
        '<div><span class="arrest-kicker">Personnel standings</span><h2 id="arrest-rankings-title">Rankings</h2></div>',
        '<p>Ranked by arrest credits, then final blows and case value.</p>',
        '</div>',
        '<div class="arrest-table-wrap"><table>',
        '<thead><tr><th scope="col">Rank</th><th scope="col">Personnel</th><th class="arrest-number" scope="col">Arrests</th><th class="arrest-number" scope="col">Final blows</th><th class="arrest-number" scope="col">Case value</th></tr></thead>',
        '<tbody>',
    ])

    for officer in rankings:
        character_id = int(officer['character_id'])
        name = escape(officer['name'])
        rank = escape(officer['rank'])
        placement = int(officer['placement'])
        sections.extend([
            '<tr>',
            f'<td class="arrest-placement" data-label="Rank">#{placement}</td>',
            '<th scope="row" data-label="Personnel">',
            f'<a class="arrest-personnel" href="https://zkillboard.com/character/{character_id}/" target="_blank" rel="noopener noreferrer">',
            f'<img src="https://images.evetech.net/characters/{character_id}/portrait?size=64" width="48" height="48" loading="lazy" alt="">',
            f'<span><strong>{name}</strong><small>{rank}</small></span>',
            '</a>',
            '</th>',
            f'<td class="arrest-number" data-label="Arrests">{int(officer["arrests"]):,}</td>',
            f'<td class="arrest-number" data-label="Final blows">{int(officer["final_blows"]):,}</td>',
            f'<td class="arrest-number" data-label="Case value">{escape(format_isk(officer["case_value"]))}</td>',
            '</tr>',
        ])

    if not rankings:
        sections.append('<tr><td class="arrest-ranking-empty" colspan="5">No personnel met the weekly arrest quota.</td></tr>')

    sections.extend([
        '</tbody></table></div>',
        '<p class="arrest-quota-note">For those meeting or exceeding the quota of 5 arrests per week</p>',
        '</section>',
        '<section class="top-dirtbags" aria-labelledby="top-dirtbags-title">',
        '<div class="arrest-section-heading">',
        '<div><span class="arrest-kicker">Most wanted</span><h2 id="top-dirtbags-title">Top 25 Dirtbags</h2></div>',
        '<p>Ranked by arrests, then total case value.</p>',
        '</div>',
        '<div class="arrest-table-wrap"><table class="dirtbag-table">',
        '<thead><tr><th scope="col">Rank</th><th scope="col">Dirtbag</th><th class="arrest-number" scope="col">Arrests</th><th class="arrest-number" scope="col">Case value</th><th class="arrest-number public-record" scope="col">Public Record</th></tr></thead>',
        '<tbody>',
    ])

    for dirtbag in dirtbags:
        character_id = int(dirtbag['character_id'])
        loss = dirtbag['most_expensive_loss']
        killmail_id = int(loss['killmail_id'])
        sections.extend([
            '<tr>',
            f'<td class="arrest-placement" data-label="Rank">#{int(dirtbag["placement"])}</td>',
            '<th scope="row" data-label="Dirtbag">',
            f'<a class="arrest-personnel" href="https://zkillboard.com/character/{character_id}/" target="_blank" rel="noopener noreferrer">',
            f'<img src="https://images.evetech.net/characters/{character_id}/portrait?size=64" width="48" height="48" loading="lazy" alt="">',
            f'<span><strong>{escape(dirtbag["name"])}</strong><small>{escape(dirtbag["corporation_name"])}</small></span>',
            '</a>',
            '</th>',
            f'<td class="arrest-number" data-label="Arrests"><strong>{int(dirtbag["arrests"]):,}</strong></td>',
            f'<td class="arrest-number" data-label="Case value">{escape(format_isk(dirtbag["total_value"]))}</td>',
            '<td class="arrest-number public-record" data-label="Public Record">',
            f'<a class="dirtbag-loss" href="https://zkillboard.com/kill/{killmail_id}/" target="_blank" rel="noopener noreferrer">',
            f'<span>{escape(loss["ship_name"])}</span><strong>{escape(format_isk(loss["total_value"]))} ↗</strong>',
            '</a>',
            '</td>',
            '</tr>',
        ])

    if not dirtbags:
        sections.append('<tr><td class="arrest-ranking-empty" colspan="5">No dirtbags were arrested during this reporting period.</td></tr>')

    sections.extend([
        '</tbody></table></div>',
        '</section>',
        '<p class="arrests-attribution">Killmail data: <a href="https://zkillboard.com/" target="_blank" rel="noopener noreferrer">zKillboard</a>. Names and universe metadata: EVE Online ESI.</p>',
    ])
    return '\n'.join(sections)


def get_content(filename):
    """Get content from .content.html file in templates directory."""
    content_file = TEMPLATE_DIR / filename.replace('.html', '.content.html')
    
    if not content_file.exists():
        print(f"Warning: Content file not found: {content_file}")
        return None
    
    with open(content_file, 'r', encoding='utf-8') as f:
        return f.read().strip()


def build_page(template_path, output_path, title, content):
    """Build a page from template with given title and content."""
    with open(template_path, 'r', encoding='utf-8') as f:
        template = f.read()
    
    # Replace markers
    output = template.replace(TITLE_MARKER, title)
    output = output.replace(CONTENT_MARKER, content)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(output)
    
    print(f"Built: {output_path}")


def main():
    """Build all pages from templates."""
    base_template = TEMPLATE_DIR / 'base.html'
    
    if not base_template.exists():
        print(f"Error: Template not found at {base_template}")
        return
    
    # Ensure output directory exists
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    print("Building pages from templates for GitHub Pages...")
    print(f"Templates: {TEMPLATE_DIR.absolute()}")
    print(f"Output: {OUTPUT_DIR.absolute()}\n")
    
    built_count = 0
    for filename, title in PAGES:
        output_file = OUTPUT_DIR / filename
        
        # Get content from .content.html file
        content = get_content(filename)
        
        if content is None:
            print(f"Skipping: {filename}")
            continue

        if filename == 'Arrests.html':
            content = content.replace('{{ARRESTS_CONTENT}}', render_arrests_content())
        
        # Build the page
        build_page(base_template, output_file, title, content)
        built_count += 1
    
    print(f"\n✓ Build complete! Generated {built_count} pages in docs/")
    print("Ready for GitHub Pages deployment from docs/ directory.")


if __name__ == '__main__':
    main()
