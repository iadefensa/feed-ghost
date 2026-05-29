# IA Defensa Feed Ghost

A dual-purpose feed anonymization tool for browsing and “anonymizing” RSS/Atom feeds via the [Internet Archive](https://web.archive.org/)—useful to avoid subscribing to sites that may excessively track you or otherwise not match your values.

1. [**Interactive feed viewer:**](https://iadefensa.github.io/feed-ghost/) A tool where you enter any feed URL and browse its entries, with each item linked to `web.archive.org` instead of the original site.
2. **Automated feed anonymization service:** Fork this repo, configure one or more feeds to follow, and a weekly GitHub Action fetches them, rewrites all item links to `web.archive.org`, and publishes the modified feeds to your own GitHub Pages site so that you can follow the URLs in your feed reader.

## 1. Using the Interactive Feed Viewer

Visit [Feed Ghost](https://iadefensa.github.io/feed-ghost/) and paste any RSS or Atom feed URL into the input field. The tool will:

1. Fetch the feed (with a CORS proxy fallback if needed)
2. Display all entries with their titles and dates
3. Link each entry to `https://web.archive.org/web/[original URL]` for anonymous access
4. Show a secondary “Save to archive” link (`https://web.archive.org/save/[original URL]`) to trigger archiving of pages not yet captured

No data is stored or transmitted beyond what’s necessary to fetch and display the feed.

## 2. Setting Up Your Own Automated Feed Anonymization Service

This requires a GitHub account and takes about five minutes.

**Privacy note:** GitHub Pages is free only for public repositories. If your fork is public—which is required for free GitHub Pages—your `config.json` and the list of feeds you follow will be publicly visible. Keep this in mind before adding feeds you’d prefer not to disclose.

### a. Fork This Repository

Click **Fork** on the GitHub repository page. All subsequent steps happen in your fork.

### b. Create and Edit `config.json`

Copy `config.example.json` to `config.json` and replace the example entry with your feeds:

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

Once done, commit the changes to your fork.

Working with a copy allows you to work on your fork and still pull updates from [the original repository](https://github.com/iadefensa/feed-ghost/).

**Fields:**

| Field | Required | Description |
| --- | --- | --- |
| `url` | Yes | Full URL to an RSS 2.0 or Atom feed |
| `name` | No | Display name for the feed. Falls back to the feed’s `<title>` if omitted |

**Changing the schedule:**

The `schedule` field in your `config.json` is for reference only. The actual schedule is set in `.github/workflows/feeds.yml`—find the `cron:` line and edit it there. The value is a standard cron expression; `0 9 * * 1` means every Monday at 09:00 UTC. Use [crontab.guru](https://crontab.guru/) to build a custom expression.

**Note:** Avoid running jobs more often than needed. Private repositories and self-hosted or billed runners may consume a quota or incur charges.

### c. Enable GitHub Pages

1. Go to your fork’s **Settings → Pages**. (If Actions are disabled in your fork, enable them first under
**Actions → Enable**.)
2. Under **Source**, select **Deploy from a branch**.
3. Choose branch: `main`, folder: `/ (root)`.
4. Click **Save**.

Your feeds will be available at `https://[your-username].github.io/feed-ghost/feeds/`.

### d. Run the Action for the First Time

The Action runs automatically each week, but you can trigger it immediately:

1. Go to **Actions → Update feeds**
2. Click **Run workflow → Run workflow**

The Action will fetch your configured feeds, rewrite their item links, and commit the results to `feeds/` and a `generate-feeds.log` summary to your repository. GitHub Pages will then redeploy automatically.

### e. Locating Your Feeds

After the Action runs:

* `https://[your-username].github.io/feed-ghost/feeds/`—index of all anonymized feeds
* `https://[your-username].github.io/feed-ghost/feeds/[slug].xml`—individual anonymized feed files, where `[slug]` is derived from the feed’s `name` or title

The feed files are valid RSS/Atom XML with item links rewritten to `https://web.archive.org/web/[original URL]`. You can subscribe to the feeds in any feed reader.

## Notes

* **Feed format support:** RSS 2.0 and Atom are supported. Older RSS 0.9x variants may work, but other formats (RSS 1.0, JSON Feed) are not.
* **Archive availability:** Not all URLs may have an archived copy on `web.archive.org`. The “Save to archive” link and prefixed links will open whatever the Internet Archive has—or its “Save Page Now” interface if nothing is captured yet.
* **CORS:** Most feed servers do not send CORS headers, so the viewer automatically retries via [corsproxy.io](https://corsproxy.io/) when a direct fetch fails. When the proxy is used, your request—including your IP address and browser metadata—is sent to corsproxy.io along with the feed URL.
* **Private feeds:** Feeds behind authentication are not supported.