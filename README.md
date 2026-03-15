# AGL Fuel Rationing Early Warning Dashboard

Live dashboard that auto-updates daily at 07:00 AEST via GitHub Actions.

## Deploy in 5 steps

### 1. Create a GitHub repository

Go to https://github.com/new and create a **public** repository called `fuel-dashboard`
(must be public for free GitHub Pages — or use a paid account for private repos).

### 2. Push this code

```bash
cd fuel-dashboard
git init
git add .
git commit -m "initial deploy"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/fuel-dashboard.git
git push -u origin main
```

### 3. Enable GitHub Pages

1. Go to your repo → **Settings** → **Pages**
2. Under **Source**, select **GitHub Actions**
3. Save

### 4. Enable the workflow

Go to your repo → **Actions** tab → you may need to click **"I understand my workflows, go ahead and enable them"**

The workflow will now run automatically at 21:00 UTC (07:00 AEST) every day.

To trigger it immediately: **Actions** → **Daily fuel indicator refresh** → **Run workflow**

### 5. Access your dashboard

Your dashboard will be live at:
```
https://YOUR-USERNAME.github.io/fuel-dashboard/
```

(Allow 2–3 minutes after the first Actions run for Pages to deploy.)

---

## How it works

```
GitHub Actions (cron: 21:00 UTC daily)
    └── runs fetch_data.py
            ├── EIA API          → Brent crude price
            ├── RBA CSV          → AUD/USD rate
            ├── ACCC scrape      → national avg fuel price
            ├── DISR scrape      → diesel/petrol days of cover
            └── Stooq CSV        → gasoil crack spread proxy
    └── commits updated data/indicators.json
    └── deploys to GitHub Pages
```

The HTML dashboard (`index.html`) is a static file that loads `data/indicators.json`
at page load. No server, no database — just a JSON file rebuilt daily.

---

## Adding paid data sources later

When you get API access to Kpler, MarineTraffic, or Argus, add your keys as
**GitHub Secrets** (Settings → Secrets → Actions → New repository secret):

| Secret name         | Used for                              |
|---------------------|---------------------------------------|
| `MARINTRAFFIC_KEY`  | Hormuz AIS transit counts             |
| `KPLER_KEY`         | AU-bound vessel departures            |
| `ARGUS_KEY`         | Singapore crack spreads, MR freight   |
| `EIA_API_KEY`       | Higher rate limits on EIA (optional)  |

Then update `fetch_data.py` to read `os.environ["KPLER_KEY"]` etc.

---

## Updating thresholds

Edit the threshold values in `fetch_data.py` (the `status()` function calls)
and the bar config in `index.html` (the `BAR_CONFIG` object).

---

## Files

| File | Purpose |
|------|---------|
| `index.html` | Dashboard UI — loads `data/indicators.json` |
| `fetch_data.py` | Data fetcher — writes `data/indicators.json` |
| `data/indicators.json` | Output data file (committed daily by Actions) |
| `.github/workflows/daily-refresh.yml` | GitHub Actions schedule |
