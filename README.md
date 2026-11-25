# LootRadar — Next-Day Rare Flight & Livery Tracker

LootRadar is a static GitHub Pages dashboard backed by a nightly GitHub Actions pipeline. It loads tomorrow's scheduled arrivals for DCA and IAD from FlightAware AeroAPI v4, assigns airport-specific rarity, enriches aircraft with public livery/photo data, and can send rare-flight alerts through ntfy.sh.

## Cost and budget protections

FlightAware lists `GET /airports/{id}/flights/scheduled_arrivals` at **$0.005 per result set** (up to 15 records). The Personal plan currently includes up to $5/month in free API credit. The pipeline stops at an internal $4.25 monthly ceiling and $0.25 per run, leaving a buffer. It checks account-wide usage from the no-cost `/account/usage` endpoint before any arrival query and tracks local usage in `data/api_usage_ledger.json`.

This is a conservative automatic stop, not an account-level billing lock. FlightAware says usage reporting can lag around 10 minutes; other applications using the same AeroAPI account can consume the same credit. Keep the API key private and review usage in the FlightAware portal. `force_budget_override` defaults to `false`; setting it to `true` bypasses the $0.25 per-run limit, but the $4.25 monthly ceiling still applies.

The workflow asks for one result set at a time (`max_pages=1`), sleeps seven seconds between pages, and stops after 22 pages per airport. That keeps the request pace below 10 result sets/minute and caps each airport at 330 records.

## Set up FlightAware

1. Create or sign in to your [FlightAware account](https://www.flightaware.com/).
2. Open [My AeroAPI](https://www.flightaware.com/aeroapi/portal/) and choose the Personal plan for personal use. Review current pricing and usage terms before enabling API access.
3. Create an AeroAPI key in the portal. Do not put it in a source file or commit it.
4. In GitHub, open **Appolzz/Aviation → Settings → Secrets and variables → Actions → New repository secret**.
5. Add `FLIGHTAWARE_API_KEY` and paste the key into its secret value.
6. Optionally add `NTFY_TOPIC` for phone notifications. Create a private/unpredictable topic name in ntfy and subscribe to it in the ntfy app.
7. In **Settings → Pages**, choose **Deploy from a branch**, branch `main`, folder `/ (root)`.
8. In **Actions**, select **Update LootRadar Arrivals** and run it once. Later runs occur automatically each day at 00:30 UTC (7:30 PM EST / 8:30 PM EDT).

## Change airports

Edit `config/airports.json` and set `active` to one to three IATA codes. DCA and IAD are active by default. `iata_to_icao` maps common IATA codes to AeroAPI airport IDs (for example, DCA → KDCA and HND → RJTT); other U.S. codes use the `K` + IATA fallback. Add an explicit mapping for any international airport not already listed.

Airport time zones are configured in `timezone_overrides`. The script requests tomorrow from 05:15 through 23:59 in each airport's local time and converts that range to UTC. After committing a config change, use **Actions → Update LootRadar Arrivals → Run workflow** for an immediate refresh.

## Notifications, photos, and rarity

- New Rare, Epic, Legendary, and Mythic flights can be sent to ntfy; seen flight keys older than seven days are pruned.
- The pipeline caches Planespotters photo URLs in `data/photo_cache.json` and queries photos for up to 60 Uncommon+ aircraft each run. Common cards can load a photo in the browser.
- `config/rarity_rules.json` contains DCA, IAD, and DEFAULT (vacation airport) profiles and model normalization rules.
- Scheduled arrival data is not an operational airport source. AeroAPI coverage can vary by airport and aircraft.

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
