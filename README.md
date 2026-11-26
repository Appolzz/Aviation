# LootRadar — Daily Rare Flight & Livery Tracker

LootRadar is a static GitHub Pages dashboard backed by a daily GitHub Actions pipeline. At 10 p.m. America/New_York local time, it loads available scheduled arrivals for the next calendar day from 6 a.m. to 10 p.m. local at DCA and IAD using FlightAware AeroAPI v4. It assigns airport-specific rarity, enriches aircraft with public livery/photo data, and can send Uncommon and higher alerts through ntfy.sh. Flights are listed by arrival time; rarity buttons filter the list without changing that order.

## Cost and budget protections

FlightAware lists `GET /airports/{id}/flights/scheduled_arrivals` at **$0.005 per result set** (up to 15 records). The Personal plan currently includes up to $5/month in free API credit. The pipeline stops at an internal $4.25 monthly ceiling. It checks account-wide usage from the no-cost `/account/usage` endpoint before any arrival query and tracks local usage in `data/api_usage_ledger.json`.

This is a software safety stop, not an account-level billing lock. FlightAware says usage reporting can lag around 10 minutes; other applications using the same AeroAPI account can consume the same credit. Keep the API key private and review usage in the FlightAware portal. The local ledger helps account for this project's current run even while FlightAware's usage page is delayed.

The workflow asks for one result set at a time (`max_pages=1`) and follows every pagination cursor until all available results are retrieved or the monthly $4.25 ceiling is reached. It sleeps seven seconds between result sets, below the Personal plan's 10 result sets/minute limit. There is no per-run or per-airport page ceiling. If any airport fetch is interrupted, or an established airport unexpectedly returns zero timed arrivals, the run fails and keeps the last complete dashboard data instead of publishing a partial airport list. Rows without a scheduled arrival time are omitted.

## Set up FlightAware

1. Create or sign in to your [FlightAware account](https://www.flightaware.com/).
2. Open [My AeroAPI](https://www.flightaware.com/aeroapi/portal/) and choose the Personal plan for personal use. Review current pricing and usage terms before enabling API access.
3. Create an AeroAPI key in the portal. Do not put it in a source file or commit it.
4. In GitHub, open **Appolzz/Aviation → Settings → Secrets and variables → Actions → New repository secret**.
5. Add `FLIGHTAWARE_API_KEY` and paste the key into its secret value.
6. Optionally add `NTFY_TOPIC` for phone notifications. Create a private/unpredictable topic name in ntfy and subscribe to it in the ntfy app.
7. In **Settings → Pages**, choose **Deploy from a branch**, branch `main`, folder `/ (root)`.
8. In **Actions**, select **Update LootRadar Arrivals** and run it once. Later runs check for fresh data every 10 minutes from 10 p.m. through 11 p.m. America/New_York time. The workflow uses UTC schedules with a local-time guard to handle daylight saving time, avoids GitHub's busier top-of-hour minute, and skips repeat fetches once tomorrow's data is complete.

## Change airports

Edit `config/airports.json` and set `active` to one to three IATA codes. DCA and IAD are active by default. `iata_to_icao` maps common IATA codes to AeroAPI airport IDs (for example, DCA → KDCA and HND → RJTT); other U.S. codes use the `K` + IATA fallback. Add an explicit mapping for any international airport not already listed.

Airport time zones are configured in `timezone_overrides`. Each scheduled update fetches the next calendar day's arrivals from 06:00 through 22:00 in each airport's local time. The dashboard shows the arrival date and time range; flights are sorted by scheduled/revised arrival time. After committing a config change, use **Actions → Update LootRadar Arrivals → Run workflow** for an immediate refresh.

## Notifications, photos, and rarity

- New Rare, Epic, Legendary, and Mythic flights can be sent to ntfy; Uncommon flights remain on the dashboard but do not trigger notifications. Seen flight keys older than seven days are pruned.
- The pipeline caches Planespotters photo URLs in `data/photo_cache.json` and queries photos for up to 60 Uncommon+ aircraft each run. Common cards can load a photo in the browser.
- `config/rarity_rules.json` contains DCA, IAD, and DEFAULT (vacation airport) profiles and model normalization rules.
- Copa Airlines arrivals are classified Rare. Other flights are classified by aircraft type and special livery, so common regional and narrowbody aircraft stay Common regardless of operator.
- Each flight card has a **Set rarity** control. Overrides are saved in this browser and reapplied when future flight data refreshes. They do not sync to other browsers or devices.
- The source is scheduled-arrival data, not an operational airport feed. It includes available filed schedules, but cancellations, schedule changes, private aircraft, and provider coverage can still make it differ from Flightradar24 or actual operations. Gaps between scheduled arrivals may also be real quiet periods.

## Files

```text
index.html                     Static dashboard
styles.css                     Responsive dark theme and rarity cards
app.js                         Filtering, sorting, local times, photos, airport modal
config/airports.json            Active airports, ICAO mappings, time zones, presets
config/rarity_rules.json       Rarity profiles and aircraft model normalization
data/arrivals.json              Dashboard data and budget status
data/api_usage_ledger.json      Monthly local result-set and cost estimate
data/seen_flights.json          Notification deduplication state
data/photo_cache.json           Planespotters photo cache
scripts/update_arrivals.py      AeroAPI and enrichment pipeline
.github/workflows/update.yml    Daily and manual workflow
```

## Data and license notes

The dashboard uses flight data under the AeroAPI plan's terms. FlightAware's Personal license is limited to personal, home, recreational, or academic use; check the applicable license before distributing data to other people. The data files committed to this repository are visible according to the repository's visibility and GitHub Pages settings.

The FlightAware key is only used in the server-side GitHub Action. Never put it in `app.js`, HTML, or any public file.
