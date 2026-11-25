# ✈️ LootRadar — Next-Day Rare Flight & Livery Tracker

A **zero-cost, self-updating** aviation dashboard that rates tomorrow's arriving flights with **Fortnite-style rarity tiers** and sends push notifications to your phone for rare finds.

Hosted on **GitHub Pages** | Updated nightly by **GitHub Actions** | Notifications via **ntfy.sh**

---

## 🌟 Features

- **Fortnite Rarity Tiers**: Common → Uncommon → Rare → Epic → Legendary → **Mythic** (military)
- **Automatic nightly updates** at 7:30 PM EST via GitHub Actions
- **Phone push notifications** (ntfy.sh) for Rare+ flights with plane photos in the notification
- **plane-alert-db enrichment**: auto-detects special liveries, heritage paint, alliance schemes
- **Automatic Planespotters.net photo lookups** as flight cards enter view, with photographer credit
- **Arrival date beside local time** on every flight card
- **Vacation mode**: swap airports for any trip in 30 seconds
- **PWA ready**: add to home screen on iOS or Android

---

## 🚀 Setup Guide

### Step 1 — Fork / Use This Repo

Click **Use this template** (or fork it) on GitHub. Then:
1. Go to your repo → **Settings** → **Pages**
2. Set **Source** to `Deploy from a branch`, branch `main`, folder `/ (root)`
3. Click **Save** — your site will be live at `https://YOUR-USERNAME.github.io/Aviation/`

---

### Step 2 — Get a Free RapidAPI AeroDataBox Key

1. Go to [RapidAPI AeroDataBox](https://rapidapi.com/aerodatabox/api/aerodatabox)
2. Sign up free and **subscribe to the Basic plan** (400 free units/month)
3. Copy your **API key** from the "Header Parameters" section (`x-rapidapi-key`)
4. The script fetches 2 airports × 2 windows = **4 API calls/day** = ~120/month — well within the free tier

---

### Step 3 — Set Up ntfy.sh Push Notifications (Free)

1. Install the **ntfy** app on your phone:
   - iOS: [App Store](https://apps.apple.com/us/app/ntfy/id1625396347)
   - Android: [Google Play](https://play.google.com/store/apps/details?id=io.heckel.ntfy) or [F-Droid](https://f-droid.org/en/packages/io.heckel.ntfy/)
2. Choose a **unique topic name** (like `lootrada-yourname-dca` — the more unique the better for privacy)
3. In the ntfy app, **subscribe to your topic**
4. You're done — no account needed for public topics!

---

### Step 4 — Add GitHub Secrets

1. Go to your GitHub repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Add these two secrets:

| Secret Name | Value |
|---|---|
| `AERODATABOX_API_KEY` | Your RapidAPI key from Step 2 |
| `NTFY_TOPIC` | Your chosen ntfy topic name (e.g. `lootrada-yourname-dca`) |

> **Note**: `AERODATABOX_API_KEY` is required for live flight updates. If it is missing, the update stops without overwriting the current sample or live data. `NTFY_TOPIC` is optional; without it, arrivals still update but phone notifications are skipped.

---

### Step 5 — Run Your First Update

1. Go to your repo → **Actions** tab
2. Click **Update LootRadar Arrivals** in the left sidebar
3. Click **Run workflow** → **Run workflow** (green button)
4. Wait ~2 minutes for it to complete
5. Refresh your GitHub Pages site — live data should appear!

After this, the Action runs automatically every night at **7:30 PM EST**.

---

## ✈️ Swapping Airports for Vacation

You can track **up to 3 airports** at a time. To switch:

1. Open `config/airports.json` in your repo
2. Change the `"active"` array:

```json
{
  "active": ["HND", "NRT"]
}
```

3. Commit → go to **Actions** → **Run workflow** manually
4. Refresh your site in ~2 minutes

### Popular Presets

| Destination | Config |
|---|---|
| Washington D.C. (home) | `["DCA", "IAD"]` |
| Tokyo | `["HND", "NRT"]` |
| New York | `["JFK", "EWR", "LGA"]` |
| London | `["LHR", "LGW"]` |
| Los Angeles | `["LAX", "BUR"]` |
| Dubai | `["DXB"]` |
| Singapore | `["SIN"]` |

You can also click the **"Vacation / Swap Airports"** button on the site to get 1-click copyable JSON presets.

---

## 🎮 Rarity Tiers

### DCA (Reagan National) Profile
| Tier | Color | Examples |
|---|---|---|
| 👑 **Mythic** | 🔴 Crimson | C-17 Globemaster, Air Force One, F-16 |
| 🌟 **Legendary** | 🟡 Gold | Any widebody (B763, B788, B748, A388) |
| ✨ **Epic** | 🟣 Purple | Special/Heritage liveries (AA Astrojet, SW state planes), B753 |
| 💙 **Rare** | 🔵 Blue | B752, A321XLR (Mint), charter/private jets |
| 🟢 **Uncommon** | 🟢 Green | B739, E190, A220 |
| ⬜ **Common** | 🩶 Slate | B738, A321, CRJ9, E175 |

### IAD (Dulles International) Profile
| Tier | Color | Examples |
|---|---|---|
| 👑 **Mythic** | 🔴 Crimson | C-17, C-5 Galaxy, E-4B Nightwatch, KC-46 |
| 🌟 **Legendary** | 🟡 Gold | B747-8 (Air China/Lufthansa), A380, A340, MD-11 |
| ✨ **Epic** | 🟣 Purple | Alliance liveries, retro paint, special schemes |
| 💙 **Rare** | 🔵 Blue | B764, A332, A339, A35K, B77L |
| 🟢 **Uncommon** | 🟢 Green | B772, B788, B789, A333, A359, B752 |
| ⬜ **Common** | 🩶 Slate | B738, A321, CRJ9, E175, B77W (daily IAD) |

---

## 📁 File Structure

```
Aviation/
├── index.html                    # Dashboard UI (PWA)
├── styles.css                    # Fortnite-rarity dark-mode styling
├── app.js                        # Client-side filtering, search, rendering
├── requirements.txt              # Python: requests>=2.31.0
├── config/
│   ├── airports.json             # Active airports + vacation presets
│   └── rarity_rules.json        # Per-airport rarity tier definitions
├── data/
│   ├── arrivals.json             # Generated: tomorrow's flights + rarity
│   ├── seen_flights.json         # Dedup tracker for ntfy notifications
│   └── photo_cache.json          # Planespotters photo URL cache
├── scripts/
│   └── update_arrivals.py        # Data pipeline (Python 3.11+)
└── .github/
    └── workflows/
        └── update.yml            # Scheduled + manual GitHub Actions workflow
```

---

## 🛠 Customization

### Add a Custom Rarity Rule

Edit `config/rarity_rules.json` → find the airport profile → add ICAO types to the right tier:

```json
"rare": {
  "icao_types": ["B752", "A21N", "YOUR_TYPE_HERE"],
  ...
}
```

### Change the Update Time

Edit `.github/workflows/update.yml`:

```yaml
- cron: '30 0 * * *'   # 00:30 UTC = 7:30 PM EST
```

Change to any cron time. [crontab.guru](https://crontab.guru) is helpful here.

---

## 🔗 Data Sources

| Source | Use | Cost |
|---|---|---|
| [AeroDataBox (RapidAPI)](https://rapidapi.com/aerodatabox/api/aerodatabox) | Flight FIDS data | Free tier (400 units/month) |
| [plane-alert-db](https://github.com/sdr-enthusiasts/plane-alert-db) | Special livery & military detection | Free (open source) |
| [Planespotters.net API](https://www.planespotters.net/photo/api) | Aircraft photos | Free (public API) |
| [ntfy.sh](https://ntfy.sh) | Push notifications | Free (public topics) |
| [GitHub Pages](https://pages.github.com) | Frontend hosting | Free |
| [GitHub Actions](https://github.com/features/actions) | Automation (2000 min/month free) | Free |

**Total cost: $0.00/month** ✅

---

## ❓ Troubleshooting

**Site shows sample data after running the Action**  
→ Make sure `AERODATABOX_API_KEY` is set in GitHub Secrets (Settings → Secrets → Actions)

**No push notifications**  
→ Verify `NTFY_TOPIC` secret matches exactly what you subscribed to in the ntfy app  
→ Check the Action logs for ntfy errors

**GitHub Pages shows 404**  
→ Go to Settings → Pages and confirm the source branch is `main` and folder is `/ (root)`

**Action fails with API errors**  
→ Check if you've exceeded the 400 units/month AeroDataBox free tier  
→ The script uses only 4 calls/day (2 airports × 2 windows) = ~120/month safely

---

## 📱 Add to Home Screen

**iOS Safari**: Share → "Add to Home Screen"  
**Android Chrome**: Menu (⋮) → "Add to Home screen"

The app is PWA-ready with a custom icon and app title.

---

*Built with ✈️ and ❤️ using only free-tier services.*
