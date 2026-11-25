# LootRadar — 24-Hour Rare Flight & Livery Tracker

LootRadar is a static GitHub Pages dashboard backed by a daily GitHub Actions pipeline. It loads available scheduled arrivals in the next rolling 24 hours for DCA and IAD from FlightAware AeroAPI v4, excluding 10 p.m.–6 a.m. in each airport's local time to reduce API requests. It assigns airport-specific rarity, enriches aircraft with public livery/photo data, and can send rare-flight alerts through ntfy.sh. Flights are listed by arrival time; rarity buttons filter the list without changing that order.

## Cost and budget protections

FlightAware lists `GET /airports/{id}/flights/scheduled_arrivals` at **$0.005 per result set** (up to 15 records). The Personal plan currently includes up to $5/month in free API credit. The pipeline stops at an internal $4.25 monthly ceiling. It checks account-wide usage from the no-cost `/account/usage` endpoint before any arrival query and tracks local usage in `data/api_usage_ledger.json`.

This is a software safety stop, not an account-level billing lock. FlightAware says usage reporting can lag around 10 minutes; other applications using the same AeroAPI account can consume the same credit. Keep the API key private and review usage in the FlightAware portal. The local ledger helps account for this project's current run even while FlightAware's usage page is delayed.

The workflow asks for one result set at a time (`max_pages=1`) and follows every pagination cursor until all available results are retrieved or the monthly $4.25 ceiling is reached. It sleeps seven seconds between result sets, below the Personal plan's 10 result sets/minute limit. There is no per-run or per-airport page ceiling. If the monthly cap stops a run, the dashboard marks that refresh as potentially incomplete.

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

Airport time zones are configured in `timezone_overrides`. Each update uses a rolling 24-hour outlook, starting when the workflow begins, and requests only the portions between 06:00 and 22:00 local time. Flights during the excluded overnight period do not appear. The dashboard shows the outlook range in each airport's local time; flights are sorted by scheduled/revised arrival time. After committing a config change, use **Actions → Update LootRadar Arrivals → Run workflow** for an immediate refresh.

## Notifications, photos, and rarity

- New Rare, Epic, Legendary, and Mythic flights can be sent to ntfy; seen flight keys older than seven days are pruned.
- The pipeline caches Planespotters photo URLs in `data/photo_cache.json` and queries photos for up to 60 Uncommon+ aircraft each run. Common cards can load a photo in the browser.
- `config/rarity_rules.json` contains DCA, IAD, and DEFAULT (vacation airport) profiles and model normalization rules.
- Copa Airlines arrivals are classified Rare. Other airlines are at least Uncommon, except United, Delta, American, Frontier, Alaska, and Southwest; aircraft already classed above Uncommon keep the higher tier.
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
