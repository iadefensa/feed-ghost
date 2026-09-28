import importlib.util
import io
import json
import os
import shutil
import tempfile
import time
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from email.utils import formatdate
from unittest import mock

DIR_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH_SCRIPT = os.path.join(DIR_REPO, 'generate-feeds.py')

RSS = '''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Example RSS</title>
    <link>https://example.com/</link>
    <item>
      <title>One</title>
      <link>https://example.com/one</link>
      <atom:link href="https://example.com/one-atom"/>
    </item>
    <item>
      <title>Two</title>
      <link>https://web.archive.org/web/https://example.com/two</link>
    </item>
  </channel>
</rss>'''

ATOM = '''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Example Atom</title>
  <entry>
    <title>One</title>
    <link href="https://example.com/one"/>
    <link rel="alternate" href="https://example.com/one-alt"/>
    <link rel="enclosure" href="https://example.com/one.mp3"/>
  </entry>
</feed>'''


def load_script(path=PATH_SCRIPT):
    spec = importlib.util.spec_from_file_location('generate_feeds', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def http_error(code, headers=None):
    return urllib.error.HTTPError('https://example.com/', code, 'Error', headers or {}, None)


class QuietTestCase(unittest.TestCase):
    def setUp(self):
        self.fg = load_script()
        # No real waiting, but keep track of requested delays
        self.sleeps = []
        self.enterContext(mock.patch.object(self.fg.time, 'sleep', self.sleeps.append))
        self.enterContext(redirect_stdout(io.StringIO()))
        self.enterContext(redirect_stderr(io.StringIO()))


class TestHelpers(unittest.TestCase):
    def setUp(self):
        self.fg = load_script()

    def test_url_slug(self):
        self.assertEqual(self.fg.url_slug('https://Example.com/Feed/'), 'example-com-feed')
        self.assertEqual(self.fg.url_slug('https://example.com/feed?format=atom'), 'example-com-feed-format-atom')
        self.assertEqual(self.fg.url_slug('https://user:secret@example.com:8080/feed'), 'example-com-8080-feed')

    def test_archive(self):
        self.assertEqual(self.fg.archive(' https://example.com/ '), 'https://web.archive.org/web/https://example.com/')
        self.assertEqual(self.fg.archive('https://web.archive.org/web/https://example.com/'), 'https://web.archive.org/web/https://example.com/')
        self.assertEqual(self.fg.archive(''), '')

    def test_redirect_to_disallowed_scheme(self):
        handler = self.fg._SafeRedirectHandler()
        with self.assertRaises(urllib.error.URLError):
            handler.redirect_request(None, None, 301, 'Moved', {}, 'file:///etc/passwd')


class TestProcessFeed(unittest.TestCase):
    def setUp(self):
        self.fg = load_script()

    def test_rss(self):
        root, title, count = self.fg.process_feed(RSS)
        self.assertEqual((title, count), ('Example RSS', 2))
        items = root.find('channel').findall('item')
        self.assertEqual(items[0].find('link').text, 'https://web.archive.org/web/https://example.com/one')
        self.assertEqual(items[0].find(f'{{{self.fg.NS_ATOM}}}link').get('href'), 'https://web.archive.org/web/https://example.com/one-atom')
        self.assertEqual(items[1].find('link').text, 'https://web.archive.org/web/https://example.com/two')
        # Channel link points to the site, not an item, and stays as is
        self.assertEqual(root.find('channel').find('link').text, 'https://example.com/')

    def test_atom(self):
        root, title, count = self.fg.process_feed(ATOM)
        self.assertEqual((title, count), ('Example Atom', 1))
        hrefs = [link.get('href') for link in root.iter(f'{{{self.fg.NS_ATOM}}}link')]
        self.assertEqual(hrefs, [
            'https://web.archive.org/web/https://example.com/one',
            'https://web.archive.org/web/https://example.com/one-alt',
            'https://example.com/one.mp3',
        ])

    def test_html(self):
        with self.assertRaisesRegex(ValueError, 'HTML page'):
            self.fg.process_feed('<html><body>Blocked</body></html>')

    def test_invalid_xml(self):
        with self.assertRaisesRegex(ValueError, 'Invalid XML'):
            self.fg.process_feed('<rss><channel>')

    def test_unsafe_xml(self):
        with self.assertRaisesRegex(ValueError, 'Unsafe XML'):
            self.fg.process_feed('<!DOCTYPE rss [<!ENTITY x "x">]><rss><channel><title>&x;</title></channel></rss>')


class TestFetchText(unittest.TestCase):
    def setUp(self):
        self.fg = load_script()

    def fetch_bytes(self, raw):
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = raw
        opener = mock.Mock(open=mock.Mock(return_value=resp))
        with mock.patch.object(self.fg.urllib.request, 'build_opener', return_value=opener):
            return self.fg.fetch_text('https://example.com/', 30)

    def test_utf8(self):
        self.assertEqual(self.fetch_bytes('Café'.encode('utf-8')), 'Café')

    def test_latin1_fallback(self):
        self.assertEqual(self.fetch_bytes('Café'.encode('latin-1')), 'Café')


class TestFetch(QuietTestCase):
    def fake_fetch_text(self, direct, archive=()):
        """Mock fetch_text: direct raises or returns once, archive results are consumed per attempt"""
        self.requests = []
        archive = list(archive)

        def fetch_text(url, timeout):
            self.requests.append(url)
            result = archive.pop(0) if url.startswith(self.fg.ARCHIVE_WEB) else direct
            if isinstance(result, BaseException):
                raise result
            return result

        self.enterContext(mock.patch.object(self.fg, 'fetch_text', fetch_text))

    def test_direct(self):
        self.fake_fetch_text('<rss/>')
        self.assertEqual(self.fg.fetch('https://example.com/feed'), ('<rss/>', False))
        self.assertEqual(self.requests, ['https://example.com/feed'])

    def test_fallback_when_blocked(self):
        for code in (403, 429):
            with self.subTest(code=code):
                self.fake_fetch_text(http_error(code), ['<rss/>'])
                self.assertEqual(self.fg.fetch('https://example.com/feed'), ('<rss/>', True))
                self.assertEqual(self.requests[-1], 'https://web.archive.org/web/https://example.com/feed')

    def test_fallback_on_network_errors(self):
        for err in (urllib.error.URLError('timed out'), TimeoutError('timed out'), ConnectionResetError()):
            with self.subTest(err=err):
                self.fake_fetch_text(err, ['<rss/>'])
                self.assertEqual(self.fg.fetch('https://example.com/feed'), ('<rss/>', True))

    def test_no_fallback_when_missing(self):
        self.fake_fetch_text(http_error(404))
        with self.assertRaises(urllib.error.HTTPError):
            self.fg.fetch('https://example.com/feed')
        self.assertEqual(len(self.requests), 1)

    def test_archive_retries_with_backoff(self):
        self.fake_fetch_text(http_error(403), [http_error(429), urllib.error.URLError('timed out'), '<rss/>'])
        self.assertEqual(self.fg.fetch('https://example.com/feed'), ('<rss/>', True))
        self.assertEqual(len(self.requests), 4)
        backoffs = [delay for delay in self.sleeps if delay >= self.fg.ARCHIVE_BACKOFF]
        self.assertEqual(backoffs, [self.fg.ARCHIVE_BACKOFF, self.fg.ARCHIVE_BACKOFF * 2])

    def test_archive_honors_retry_after(self):
        in_90_s = formatdate(time.time() + 90, usegmt=True)
        cases = (('90', 90), (in_90_s, 90), ('Mon, 01 Jan 2024 00:00:00 GMT', self.fg.ARCHIVE_BACKOFF), ('soon', self.fg.ARCHIVE_BACKOFF))
        for retry_after, expected in cases:
            with self.subTest(retry_after=retry_after):
                self.sleeps.clear()
                self.fake_fetch_text(http_error(403), [http_error(429, {'Retry-After': retry_after}), '<rss/>'])
                self.fg.fetch('https://example.com/feed')
                # Allow for the clock ticking between formatting and parsing the date
                self.assertTrue(any(expected - 1 <= delay <= expected for delay in self.sleeps), self.sleeps)

    def test_archive_gives_up_when_retry_after_too_long(self):
        for retry_after in (str(self.fg.ARCHIVE_BACKOFF_MAX + 1), formatdate(time.time() + 3600, usegmt=True)):
            with self.subTest(retry_after=retry_after):
                self.fake_fetch_text(http_error(403), [http_error(429, {'Retry-After': retry_after})])
                with self.assertRaisesRegex(RuntimeError, 'HTTP Error 429'):
                    self.fg.fetch('https://example.com/feed')
                self.assertEqual(len(self.requests), 2)

    def test_archive_no_retry_when_missing(self):
        self.fake_fetch_text(http_error(403), [http_error(404)])
        with self.assertRaisesRegex(RuntimeError, r'Direct fetch failed \(HTTP 403\), and so did the Internet Archive fallback \(HTTP Error 404'):
            self.fg.fetch('https://example.com/feed')
        self.assertEqual(len(self.requests), 2)

    def test_archive_gives_up(self):
        failures = [http_error(503)] * self.fg.ARCHIVE_ATTEMPTS
        self.fake_fetch_text(http_error(403), failures)
        with self.assertRaisesRegex(RuntimeError, 'Internet Archive fallback'):
            self.fg.fetch('https://example.com/feed')
        self.assertEqual(len(self.requests), 1 + self.fg.ARCHIVE_ATTEMPTS)

    def test_archive_requests_are_spaced(self):
        clock = iter(range(100, 200))
        with mock.patch.object(self.fg.time, 'monotonic', lambda: next(clock)):
            self.fg.archive_wait()
            self.fg.archive_wait()
        self.assertEqual(self.sleeps, [self.fg.ARCHIVE_INTERVAL - 1])


class TestMain(QuietTestCase):
    """Runs the script from a temporary copy, as main() works relative to the script’s location"""

    def setUp(self):
        super().setUp()
        self.dir_tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir_tmp)
        self.dir_feeds = os.path.join(self.dir_tmp, 'feeds')
        path_script = os.path.join(self.dir_tmp, 'generate-feeds.py')
        shutil.copy(PATH_SCRIPT, path_script)
        self.fg = load_script(path_script)
        self.enterContext(mock.patch.object(self.fg.time, 'sleep', self.sleeps.append))

    def run_main(self, feeds, responses):
        """Run main() with responses mapping feed URLs to (text, via_archive) or an exception"""
        with open(os.path.join(self.dir_tmp, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'feeds': feeds}, f)
        self.calls = []

        def fetch(url):
            self.calls.append(('fetch', url))
            result = responses[url]
            if isinstance(result, BaseException):
                raise result
            return result

        with mock.patch.object(self.fg, 'fetch', fetch), \
                mock.patch.object(self.fg, 'trigger_save', lambda url: self.calls.append(('save', url))), \
                mock.patch.object(self.fg, 'get_config_edit_url', return_value=None):
            self.fg.main()
        return self.read_log()

    def read_log(self):
        with open(os.path.join(self.dir_tmp, 'generate-feeds.log'), encoding='utf-8') as f:
            return f.read()

    def test_generates_feeds_index_and_log(self):
        log = self.run_main(
            [{'url': 'https://example.com/rss', 'name': 'Named'}, {'url': 'https://example.com/atom'}],
            {'https://example.com/rss': (RSS, False), 'https://example.com/atom': (ATOM, True)},
        )
        with open(os.path.join(self.dir_feeds, 'example-com-rss.xml'), encoding='utf-8') as f:
            self.assertIn('https://web.archive.org/web/https://example.com/one', f.read())
        self.assertTrue(os.path.exists(os.path.join(self.dir_feeds, 'example-com-atom.xml')))
        self.assertTrue(os.path.exists(os.path.join(self.dir_feeds, 'index.html')))
        self.assertIn('Feeds: 2 processed, 0 error(s)', log)
        self.assertIn('Named → example-com-rss.xml (2 items)', log)
        self.assertIn('Example Atom → example-com-atom.xml (1 item (via Internet Archive))', log)

    def test_saves_after_all_fetches(self):
        self.run_main(
            [{'url': 'https://example.com/a'}, {'url': 'https://example.com/b'}, {'url': 'https://example.com/c'}],
            {'https://example.com/a': (RSS, True), 'https://example.com/b': (RSS, False), 'https://example.com/c': (RSS, True)},
        )
        self.assertEqual(self.calls, [
            ('fetch', 'https://example.com/a'),
            ('fetch', 'https://example.com/b'),
            ('fetch', 'https://example.com/c'),
            ('save', 'https://example.com/a'),
            ('save', 'https://example.com/c'),
        ])

    def test_failed_feed_keeps_cached_file(self):
        self.run_main([{'url': 'https://example.com/rss'}], {'https://example.com/rss': (RSS, False)})
        # Exits with an error as no feed could be fetched, but only after writing index and log
        with self.assertRaises(SystemExit):
            self.run_main([{'url': 'https://example.com/rss'}], {'https://example.com/rss': RuntimeError('Down')})
        log = self.read_log()
        self.assertTrue(os.path.exists(os.path.join(self.dir_feeds, 'example-com-rss.xml')))
        self.assertIn('Example RSS → example-com-rss.xml (not reachable, showing cached file)', log)
        self.assertIn('https://example.com/rss: Down', log)

    def test_failed_feed_without_cache(self):
        with self.assertRaises(SystemExit):
            self.run_main([{'url': 'https://example.com/rss'}], {'https://example.com/rss': RuntimeError('Down')})
        log = self.read_log()
        self.assertIn('example.com (could not be generated)', log)

    def test_deletes_stale_feeds(self):
        self.run_main([{'url': 'https://example.com/old'}], {'https://example.com/old': (RSS, False)})
        log = self.run_main([{'url': 'https://example.com/new'}], {'https://example.com/new': (RSS, False)})
        self.assertEqual(sorted(os.listdir(self.dir_feeds)), ['example-com-new.xml', 'index.html'])
        self.assertIn('Deleted: example-com-old.xml', log)

    def test_hides_credentials(self):
        with self.assertRaises(SystemExit):
            self.run_main(
                [{'url': 'https://user:secret@example.com/rss?token=secret'}],
                {'https://user:secret@example.com/rss?token=secret': RuntimeError('Down')},
            )
        log = self.read_log()
        self.assertNotIn('secret', log)
        self.assertNotIn('secret', ''.join(os.listdir(self.dir_feeds)))
        self.assertIn('https://example.com/rss: Down', log)


if __name__ == '__main__':
    unittest.main()