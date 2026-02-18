#!/usr/bin/env python3
"""
Simple template builder for WHPD website.
Generates static pages from templates for GitHub Pages deployment.
Templates are in templates/, output goes to docs/ directory.
"""

import os
import re
from pathlib import Path

# Define source and output directories
TEMPLATE_DIR = Path('templates')
OUTPUT_DIR = Path('docs')

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
    ('MemeFleet.html', 'The Wormhole Police - MemeFleet'),
    ('404.html', 'The Wormhole Police - 404'),
    ('legislation.html', 'The Wormhole Police - Legislation (Redirect)'),
    ('MarkeeDragonRedirect.html', 'The Wormhole Police - Markee Dragon Redirect'),
    ('HighsecBuybackRedirect.html', 'The Wormhole Police - Highsec Buyback Redirect'),
    ('LowsecBuybackRedirect.html', 'The Wormhole Police - Lowsec Buyback Redirect'),
    ('FreeSkillPointsRedirect.html', 'The Wormhole Police - Free Skill Points Redirect'),
]


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
        
        # Build the page
        build_page(base_template, output_file, title, content)
        built_count += 1
    
    print(f"\n✓ Build complete! Generated {built_count} pages in docs/")
    print("Ready for GitHub Pages deployment from docs/ directory.")


if __name__ == '__main__':
    main()
