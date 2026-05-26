# IA Defensa Feed Ghost

A two-part feed tool for browsing and archiving RSS/Atom feeds anonymously via the [Internet Archive](https://web.archive.org/)—useful to avoid subscribing to services that may excessively track you or otherwise not match your values.

* **Part 1—[Interactive feed viewer](@@):** A tool where you enter any feed URL and browse its entries, with each item linked to `web.archive.org` instead of the original site.
* **Part 2—Automated feed anonymization service:** Fork this repo, configure a list of feeds, and a weekly GitHub Action fetches them, rewrites all item links to `web.archive.org`, and publishes the modified feeds to your own GitHub Pages site so that you can follow the URLs in your feed reader.

## Part 1: Using the Interactive Feed Viewer

Visit [Feed Ghost](@@) and paste any RSS or Atom feed URL into the input field. The tool will:

1. Fetch the feed (with a CORS proxy fallback if needed)
2. Display all entries with their titles and dates
3. Link each entry to `https://web.archive.org/web/[original URL]` for anonymous access
4. Show a secondary “Save to archive” link (`https://web.archive.org/save/[original URL]`) to trigger archiving of pages not yet captured

No data is stored or transmitted beyond what’s necessary to fetch and display the feed.

## Part 2: Setting Up Your Own Automated Feed Anonymization Service

This requires a GitHub account and takes about five minutes.

### 1. Fork This Repository

Click **Fork** on the GitHub repository page. All subsequent steps happen in your fork.

### 2. Edit `config.json`

Open `config.json` in your fork and replace the example entry with your feeds:

```json
{
  "schedule": "0 9 * * 1",
  "feeds": [
    {
      "url": "https://example.com/feed.xml",
      "name": "Example Blog"
    },
    {
      "url": "https://another.com/rss"
    }
  ]
}
```

**Fields:**

| Field | Required | Description |
| --- | --- | --- |
| `url` | Yes | Full URL to an RSS 2.0 or Atom feed |
| `name` | No | Display name for the feed. Falls back to the feed’s own `<title>` if omitted |

**Changing the schedule:**

The `schedule` field in `config.json` is for reference only. The actual schedule is set in `.github/workflows/feeds.yml`—find the `cron:` line and edit it there. The value is a standard cron expression; `0 9 * * 1` means every Monday at 09:00 UTC. Use [crontab.guru](https://crontab.guru/) to build a custom expression.

### 3. Enable GitHub Pages

1. Go to your fork’s **Settings → Pages**
2. Under **Source**, select **Deploy from a branch**
3. Choose branch: `main`, folder: `/ (root)`
4. Click **Save**

Your site will be available at `https://[your-username].github.io/feed-ghost/`.

### 4. Run the Action for the First Time

The Action runs automatically each week, but you can trigger it immediately:

1. Go to **Actions → Update archived feeds**
2. Click **Run workflow → Run workflow**

The Action will fetch your configured feeds, rewrite their item links, and commit the results to `feeds/` in your repository. GitHub Pages will then redeploy automatically.

### 5. Finding Your Feeds

After the Action runs:

* `https://[your-username].github.io/feed-ghost/feeds/`—index of all archived feeds
* `https://[your-username].github.io/feed-ghost/feeds/[slug].xml`—individual archived feed files, where `[slug]` is derived from the feed’s `name` or title

The feed files are valid RSS/Atom XML with item links rewritten to `https://web.archive.org/web/[original URL]`. You can subscribe to them in any feed reader.

## Notes

* **Feed format support:** RSS 2.0 and Atom are supported. Other formats (RSS 1.0, JSON Feed) are not.
* **Archive availability:** Not all URLs may have an archived copy on `web.archive.org`. The “Save to archive” link (Part 1) and prefixed links (Part 2) will open whatever the Internet Archive has—or its “Save Page Now” interface if nothing is captured yet.
* **CORS (Part 1):** Most feed servers do not send CORS headers, so the viewer automatically retries via [corsproxy.io](https://corsproxy.io/) when a direct fetch fails. The proxy sees only the feed URL you enter.
* **Private feeds:** Feeds behind authentication are not supported.