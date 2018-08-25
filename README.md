[![Version](https://img.shields.io/badge/version-0.0.1-green.svg?style=for-the-badge)](#) [![mantained](https://img.shields.io/maintenance/yes/2018.svg?style=for-the-badge)](#)

[![maintainer](https://img.shields.io/badge/maintainer-Ian%20Richardson%20%40iantrich-blue.svg?style=for-the-badge)](#)


# sensor.feedparser
RSS feed custom component for Home Assistant which can be used in conjunction with the custom Lovelace [list-card](https://github.com/custom-cards/list-card)

To get started put `/custom_components/sensor/feedparser.py` here:
`<config directory>/custom_components/sensor/feedparser.py`

**Example configuration.yaml:**

```yaml
sensor:
  platform: feedparser
  name: Engineering Feed
  feed_url: 'https://www.sciencedaily.com/rss/matter_energy/engineering.xml'
  date_format: '%a, %b %d %I:%M %p'
  inclusions:
    - title
    - link
    - description
    - image
    - language
    - pubDate
  exclusions:
    - language
```

**Configuration variables:**

key | description
:--- | :---
**platform (Required)** | The platform name
**name (Required)** | Name your feed
**feed_url (Required)** | The RSS feed URL
**date_format (Optional)** | strftime date format for date strings **Default** `%a, %b %d %I:%M %p`
**inclusions (Optional)** | List of fields to include from populating the list
**exclusions (Optional)** | List of fields to exclude from populating the list

***

Note: Will return all fields if no inclusions or exclusions are specified

Due to how `custom_componentes` are loaded, it is normal to see a `ModuleNotFoundError` error on first boot after adding this, to resolve it, restart Home-Assistant.

## Support
Hey dude! Help me out for a couple of :beers: or a :coffee:!

[![coffee](https://www.buymeacoffee.com/assets/img/custom_images/black_img.png)](https://www.buymeacoffee.com/zJtVxUAgH)
