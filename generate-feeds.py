#!/usr/bin/env python3
"""
IA Defensa Feed Ghost Automated Feed Anonymization Service.
Reads config.json, fetches each configured feed, rewrites item links to
web.archive.org, and writes output feed files to feeds/.
"""

import json
import os
import re
import subprocess
import sys
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import defusedxml.ElementTree as safe_ET
from defusedxml import DefusedXmlException
from datetime import datetime, timezone
from html import escape
from urllib.parse import urlparse

ARCHIVE_WEB = 'https://web.archive.org/web/'
ARCHIVE_SAVE = 'https://web.archive.org/save/'

NS_ATOM = 'http://www.w3.org/2005/Atom'
NS_CONTENT = 'http://purl.org/rss/1.0/modules/content/'
NS_DC = 'http://purl.org/dc/elements/1.1/'
NS_MEDIA = 'http://search.yahoo.com/mrss/'
NS_SY = 'http://purl.org/rss/1.0/modules/syndication/'

ET.register_namespace('atom', NS_ATOM)
ET.register_namespace('content', NS_CONTENT)
ET.register_namespace('dc', NS_DC)
ET.register_namespace('media', NS_MEDIA)
ET.register_namespace('sy', NS_SY)


def get_config_edit_url(repo_root):
    try:
        remote = subprocess.check_output(
            ['git', 'remote', 'get-url', 'origin'],
            cwd=repo_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        match = re.search(r'github\.com[:/](.+?/[^/]+?)(?:\.git)?$', remote)
        if match:
            return f'https://github.com/{match.group(1)}/edit/main/config.json'
    except Exception:
        pass
    return None


def slugify(text):
    text = re.sub(r'[^\w\s-]', '', text.lower().strip())
    slug = re.sub(r'[\s_-]+', '-', text).strip('-')
    return slug or 'feed'


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme not in ('http', 'https'):
            raise urllib.error.URLError(f'Redirect to disallowed scheme: {urlparse(newurl).scheme!r}')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def trigger_save(url):
    """Request a new Internet Archive snapshot of url (fire-and-forget)."""
    req = urllib.request.Request(
        f'{ARCHIVE_SAVE}{url}',
        headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36'},
    )
    try:
        with urllib.request.urlopen(req, timeout=15):
            pass
        print(f'  Triggered Internet Archive re-archive for {url}')
    except Exception as save_err:
        print(f'  Could not trigger Internet Archive save: {save_err}')


def fetch(url, *, _archive_fallback=True):
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
            'Accept': 'application/rss+xml, application/atom+xml, application/xml, text/xml, */*',
        },
    )
    opener = urllib.request.build_opener(_SafeRedirectHandler)
    try:
        with opener.open(req, timeout=30) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as err:
        if _archive_fallback and err.code in (403, 429):
            print(f'  Direct fetch blocked (HTTP {err.code}); trying Internet Archive fallback…')
            try:
                text, _ = fetch(ARCHIVE_WEB + url, _archive_fallback=False)
            except urllib.error.URLError:
                print(f'  Internet Archive timed out, retrying…')
                text, _ = fetch(ARCHIVE_WEB + url, _archive_fallback=False)
            trigger_save(url)
            return text, True
        raise
    except urllib.error.URLError as err:
        if _archive_fallback:
            print(f'  Direct fetch failed ({err.reason}); trying Internet Archive fallback…')
            try:
                text, _ = fetch(ARCHIVE_WEB + url, _archive_fallback=False)
            except urllib.error.URLError:
                print(f'  Internet Archive timed out, retrying…')
                text, _ = fetch(ARCHIVE_WEB + url, _archive_fallback=False)
            trigger_save(url)
            return text, True
        raise
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        text = raw.decode('latin-1', errors='replace')
    return text, False


def archive(url):
    url = url.strip()
    if not url or url.startswith(ARCHIVE_WEB):
        return url
    return ARCHIVE_WEB + url


def process_rss(root):
    channel = root if root.tag == 'channel' else root.find('channel')
    if channel is None:
        return None, 0

    title_el = channel.find('title')
    feed_title = title_el.text.strip() if title_el is not None and title_el.text else None

    count = 0
    for item in channel.findall('item'):
        count += 1
        link_el = item.find('link')
        if link_el is not None and link_el.text:
            link_el.text = archive(link_el.text.strip())
        # atom:link fallback used by some RSS feeds
        atom_link = item.find(f'{{{NS_ATOM}}}link')
        if atom_link is not None:
            href = atom_link.get('href', '').strip()
            if href:
                atom_link.set('href', archive(href))

    return feed_title, count


def process_atom(root):
    ET.register_namespace('', NS_ATOM)

    title_el = root.find(f'{{{NS_ATOM}}}title')
    feed_title = title_el.text.strip() if title_el is not None and title_el.text else None

    count = 0
    for entry in root.findall(f'{{{NS_ATOM}}}entry'):
        count += 1
        for link in entry.findall(f'{{{NS_ATOM}}}link'):
            rel = link.get('rel', 'alternate')
            if rel in ('alternate', ''):
                href = link.get('href', '').strip()
                if href:
                    link.set('href', archive(href))

    return feed_title, count


def process_feed(xml_text):
    try:
        root = safe_ET.fromstring(xml_text)
    except DefusedXmlException as err:
        raise ValueError(f'Unsafe XML: {err}') from err
    except ET.ParseError as err:
        raise ValueError(f'Invalid XML: {err}') from err

    tag = root.tag
    if tag == f'{{{NS_ATOM}}}feed' or tag == 'feed':
        feed_title, count = process_atom(root)
        return root, feed_title, count
    elif 'rss' in tag or tag == 'channel':
        feed_title, count = process_rss(root)
        return root, feed_title, count
    else:
        # Try RSS as fallback (many feeds use unrecognised root tags)
        feed_title, count = process_rss(root)
        return root, feed_title, count


def write_feed(root, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tree = ET.ElementTree(root)
    ET.indent(tree, space='  ')
    tree.write(path, encoding='unicode', xml_declaration=True)


def generate_index(feeds_info, out_path, now_str, config_edit_url=None):
    if feeds_info:
        items_html = '\n'.join(
            f'\t\t\t\t\t<li class="entry">'
            f'\t\t\t\t\t\t<a href="{escape(info["filename"])}" target="_blank">{escape(info["title"])}</a>'
            f' <span>{info["count"]} item{"s" if info["count"] != 1 else ""}</span>'
            + (' <span>· delayed (falling back to latest Internet Archive snapshot)</span>' if info.get("via_archive") else '')
            + '\n\t\t\t\t\t</li>'
            for info in feeds_info
        )
        list_html = f'\t\t\t\t<ul class="list-none m-0 p-0">\n{items_html}\n\t\t\t\t</ul>'
    else:
        list_html = '\t\t\t\t<p class="text-sm py-4">No feeds have been generated yet.</p>'

    html = f'''<!DOCTYPE html>
<html lang="en" class="dark">
\t<head>
\t\t<meta charset="utf-8">
\t\t<meta name="viewport" content="width=device-width, initial-scale=1.0">
\t\t<title>“Anonymized” Feeds</title>
\t\t<link rel="stylesheet" href="../setup/default.css">
\t\t<link rel="stylesheet" href="../setup/basecoat.min.css">
\t\t<script src="../setup/tailwind.min.js"></script>
\t\t<style>
\t\t\tspan {{
\t\t\t\tcolor: #9ca3af;
\t\t\t\tfont-size: 75%;
\t\t\t}}

\t\t\tspan:not(span + span) {{
\t\t\t\tmargin-left: .75rem;
\t\t\t}}

\t\t\t.entry {{
\t\t\t\tborder-bottom: 1px solid #333;
\t\t\t\tpadding: .75rem 0;
\t\t\t}}

\t\t\t.entry:last-child {{
\t\t\t\tborder-bottom: none;
\t\t\t}}
\t\t</style>
\t</head>
\t<body class="bg-zinc-900 pb-3 pt-8 px-4">
\t\t<div class="max-w-3xl mx-auto p-4">
\t\t\t<h1 class="mb-2 text-2xl">“Anonymized” Feeds</h1>
\t\t\t<p class="mb-8 text-sm">Copies of {'<a href="' + escape(config_edit_url) + '">configured feeds</a>' if config_edit_url else 'configured feeds'} with item links rewritten to <a href="https://web.archive.org/" target="_blank">the Internet Archive</a>. Last updated: {now_str}.</p>
\t\t\t<section class="border border-[#333] mb-8 px-6 py-2 rounded-md">
{list_html}
\t\t\t</section>
\t\t\t<p class="mt-5">This is a custom fork of <a href="https://github.com/iadefensa/feed-ghost/" target="_blank">a digital defense tool</a> by <a href="https://iadefensa.com/" target="_blank">IA Defensa</a>.</p>
\t\t</div>
\t</body>
</html>'''

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)


def main():
    repo_root = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(repo_root, 'config.json')
    feeds_dir = os.path.join(repo_root, 'feeds')

    if not os.path.exists(config_path):
        print('config.json not found; nothing to do. Copy config.example.json to config.json to configure feeds.', file=sys.stderr)
        sys.exit(0)

    with open(config_path, encoding='utf-8') as f:
        config = json.load(f)

    feeds = config.get('feeds', [])
    if not feeds:
        print('No feeds configured in config.json.')
        sys.exit(0)

    now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    feeds_info = []
    errors = []
    used_slugs = set()

    for feed_cfg in feeds:
        url = feed_cfg.get('url', '').strip()
        if not url:
            continue
        name_hint = feed_cfg.get('name', '').strip()
        print(f'Processing: {url}')

        try:
            xml_text, via_archive = fetch(url)
            root, feed_title, count = process_feed(xml_text)
            display_name = name_hint or feed_title or urlparse(url).netloc or 'Feed'
            base = slugify(name_hint or feed_title or urlparse(url).netloc)
            slug, n = base, 1
            while slug in used_slugs:
                n += 1
                slug = f'{base}-{n}'
            used_slugs.add(slug)
            filename = f'{slug}.xml'
            out_path = os.path.join(feeds_dir, filename)
            write_feed(root, out_path)
            feeds_info.append({'title': display_name, 'filename': filename, 'count': count, 'via_archive': via_archive})
            print(f'  → feeds/{filename} ({count} item{"s" if count != 1 else ""})')
        except Exception as err:
            print(f'  ERROR: {err}', file=sys.stderr)
            errors.append({'url': url, 'error': str(err)})

    config_edit_url = get_config_edit_url(repo_root)
    generate_index(feeds_info, os.path.join(feeds_dir, 'index.html'), now_str, config_edit_url)
    print(f'\nDone. {len(feeds_info)} feed(s) processed, {len(errors)} error(s).')

    log_lines = [f'Last run: {now_str}', f'Feeds: {len(feeds_info)} processed, {len(errors)} error(s)']
    for info in feeds_info:
        via = ' (via Internet Archive)' if info.get('via_archive') else ''
        log_lines.append(f'  · {info["title"]} → {info["filename"]} ({info["count"]} item{"s" if info["count"] != 1 else ""}{via})')
    if errors:
        log_lines.append('Errors:')
        for err in errors:
            parsed = urlparse(err['url'])
            hostname = parsed.hostname or ''
            if ':' in hostname:
                hostname = f'[{hostname}]'
            safe_netloc = hostname
            if parsed.port:
                safe_netloc += f':{parsed.port}'
            safe_url = parsed._replace(netloc=safe_netloc, query='', fragment='').geturl()
            log_lines.append(f'  · {safe_url}: {err["error"]}')
    with open(os.path.join(repo_root, 'generate-feeds.log'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(log_lines) + '\n')

    if errors:
        print('\nErrors:')
        for err in errors:
            print(f'  {err["url"]}: {err["error"]}')
        if not feeds_info:
            sys.exit(1)


if __name__ == '__main__':
    main()
