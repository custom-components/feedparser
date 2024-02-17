# sensor.feedparser
RSS feed custom component for [Home Assistant](https://www.home-assistant.io/) which can be used in conjunction with the custom [Lovelace](https://www.home-assistant.io/lovelace) [list-card](https://github.com/custom-cards/list-card)

[![GitHub Release][releases-shield]][releases]
[![License][license-shield]](LICENSE.md)

![Project Maintenance][maintenance-shield]
[![GitHub Activity][commits-shield]][commits]

[![Discord][discord-shield]][discord]
[![Community Forum][forum-shield]][forum]

## Support
Hey dude! Help me out for a couple of :beers: or a :coffee:!

[![coffee](https://www.buymeacoffee.com/assets/img/custom_images/black_img.png)](https://www.buymeacoffee.com/zJtVxUAgH)


## Installation
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

1. Open HACS Settings and add this repository (https://github.com/custom-components/feedparser/)
   as a Custom Repository (use **Integration** as the category).
2. The `feedparser` page should automatically load (or find it in the HACS Store)
3. Click `Install`

Alternatively, click on the button below to add the repository:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?category=Integration&repository=feedparser&owner=custom-components)


## Configuration

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

If you wish the integration to look for enclosures in the feed entries, add `image` to `inclusions` list. Do not use `enclosure`.
The integration tries to get the link to an image for the given feed item and stores it under the attribute named `image`. If it fails to find it, it assigns the Home Assistant logo to it instead.

Note that the original `pubDate` field is available under `published` attribute for the given feed entry. Other date-type values that can be available are `updated`, `created` and `expired`. Please refer to [the documentation of the original feedparser](https://feedparser.readthedocs.io/en/latest/date-parsing.html) library.

**Configuration variables:**

key | description
:--- | :---
**platform (Required)** | The platform name
**name (Required)** | Name your feed
**feed_url (Required)** | The RSS feed URL
**date_format (Optional)** | strftime date format for date strings **Default** `%a, %b %d %I:%M %p`
**local_time (Optional)** | Whether to convert date into local time **Default** false
**show_topn (Optional)** | fetch how many entres from rss source，if not set then fetch all
**inclusions (Optional)** | List of fields to include from populating the list
**exclusions (Optional)** | List of fields to exclude from populating the list
**scan_interval (Optional)** | Update interval in hours

***

Note: Will return all fields if no inclusions or exclusions are specified

Due to how `custom_components` are loaded, it is normal to see a `ModuleNotFoundError` error on first boot after adding this, to resolve it, restart Home-Assistant.

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
