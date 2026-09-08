# sensor.feedparser
RSS feed custom component for [Home Assistant](https://www.home-assistant.io/) which can be used in conjunction with the custom [Lovelace](https://www.home-assistant.io/lovelace) [list-card](https://github.com/custom-cards/list-card)

[![GitHub Release][releases-shield]][releases]
[![License][license-shield]](LICENSE.md)

![Project Maintenance][maintenance-shield]
[![GitHub Activity][commits-shield]][commits]

[![Discord][discord-shield]][discord]
[![Community Forum][forum-shield]][forum]

## Installation
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

1. Open HACS Settings and add this repository (https://github.com/custom-components/feedparser/)
   as a Custom Repository (use **Integration** as the category).
2. The `feedparser` page should automatically load (or find it in the HACS Store)
3. Click `Install`

Alternatively, click on the button below to add the repository:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?category=Integration&repository=feedparser&owner=custom-components)


## Configuration

### UI configuration (recommended)

1. Go to **Settings** -> **Devices & Services** -> **Integrations**.
2. Click **Add Integration** and search for **Feedparser**.
3. Fill in at least `Name` and `Feed URL`.
4. Set the refresh interval with the duration field (minimum 1 minute).
5. Optional include/exclude fields are entered as comma-separated values.

To update refresh or parsing behavior later, open the Feedparser integration card and use **Configure** (options flow). Saved changes reload only that feed entry so the new settings take effect immediately.

### YAML configuration (legacy)

**Example configuration.yaml:**

```yaml
sensor:
  - platform: feedparser
    name: Engineering Feed
    feed_url: 'https://www.sciencedaily.com/rss/matter_energy/engineering.xml'
    date_format: '%a, %d %b %Y %H:%M:%S %Z'
    scan_interval:
      hours: 3
    inclusions:
      - title
      - link
      - description
      - image
      - published
    exclusions:
      - language

  # Configuration of the second sensor tracking a different RSS feed
  - platform: feedparser
    name: Algemeen
    feed_url: https://www.nu.nl/rss/Algemeen
    local_time: true
    show_topn: 1
```

If you wish the integration to look for enclosures in the feed entries, add `image` to the `inclusions` list. Do not use `enclosure`.
The integration tries to extract an image URL and stores it under the `image` attribute. If no image can be found, it uses the Home Assistant logo as a fallback.

Note that the original `pubDate` field is available under `published`. Other date-like fields that may be present are `updated`, `created`, and `expired`. Refer to the original [feedparser date parsing documentation](https://feedparser.readthedocs.io/en/latest/date-parsing.html) for feed-specific details.

### Configuration reference

The integration supports both UI setup (recommended) and legacy YAML setup. Most options are the same in both paths.

| Key | Required | Type | Default | Example | What it does |
| :-- | :-- | :-- | :-- | :-- | :-- |
| `platform` (YAML only) | Yes (YAML) | string | - | `feedparser` | Home Assistant platform name used in YAML mode. |
| `name` | Yes | string | - | `Engineering Feed` | Name shown for the sensor entity. |
| `feed_url` | Yes | URL string | - | `https://www.nu.nl/rss/Algemeen` | RSS/Atom feed URL to fetch and parse. Supports `http`, `https`, and `file` in dev/testing. |
| `date_format` | No | string (`strftime`) | `%a, %b %d %I:%M %p` | `%a, %d %b %Y %H:%M:%S %Z` | Output format for date fields in feed entries. |
| `local_time` | No | boolean | `false` | `true` | Converts parsed date values from feed timezone to Home Assistant local timezone. |
| `scan_interval` | No | duration object | `1 hour` | `{ hours: 1, minutes: 30 }` | Polling interval for refreshing feed data. UI input must be at least 1 minute. |
| `show_topn` | No | integer | `9999` | `10` | Maximum number of entries exposed in sensor attributes. |
| `remove_summary_image` | No | boolean | `false` | `true` | Strips `<img ...>` tags from the `summary` field. |
| `inclusions` | No | list of strings (YAML) / comma-separated string (UI) | all fields | `title, link, published, image` | If set, only listed fields are kept for each entry. |
| `exclusions` | No | list of strings (YAML) / comma-separated string (UI) | none | `summary, language` | Fields to remove from each entry after parsing. |

### Notes and behavior details

- **`inclusions` vs `exclusions`**: If `inclusions` is set, only those fields are considered. `exclusions` then removes fields from that resulting set.
- **When neither `inclusions` nor `exclusions` is set**: all available feed fields are returned.
- **`image` extraction**: adding `image` to `inclusions` enables image URL extraction from enclosures or summary HTML.
- **UI vs YAML input format**:
  - UI uses comma-separated text for `inclusions` and `exclusions`.
  - YAML uses proper lists.
  - UI uses a single duration control for `scan_interval`; YAML uses `scan_interval` object keys such as `hours` and `minutes`.
- **Date parsing**: if a feed date is malformed, parser behavior depends on feed content and fallback parsing.

Due to how `custom_components` are loaded, it is normal to see a `ModuleNotFoundError` error on first boot after adding this, to resolve it, restart Home-Assistant.

## Development Container

This repository includes a devcontainer inspired by the `custom-components/readme` blueprint.

1. Open the repo in VS Code.
2. Run **Dev Containers: Reopen in Container**.
3. After dependencies install, run `bash scripts/develop` to start Home Assistant with `test_hass`.

[commits-shield]: https://img.shields.io/github/commit-activity/y/custom-components/feedparser.svg?style=for-the-badge
[commits]: https://github.com/custom-components/feedparser/commits/master
[discord]: https://discord.gg/Qa5fW2R
[discord-shield]: https://img.shields.io/discord/330944238910963714.svg?style=for-the-badge
[forum-shield]: https://img.shields.io/badge/community-forum-brightgreen.svg?style=for-the-badge
[forum]: https://community.home-assistant.io/t/custom-component-rss-feed-parser/64637
[license-shield]: https://img.shields.io/github/license/custom-components/feedparser.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-Ondrej%20Gajdusek%20%40ogajduse-blue.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/custom-components/feedparser.svg?style=for-the-badge
[releases]: https://github.com/custom-components/feedparser/releases
