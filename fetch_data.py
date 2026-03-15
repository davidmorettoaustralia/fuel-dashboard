#!/usr/bin/env python3
"""
AGL Fuel Rationing Early Warning — Daily Data Fetcher
Pulls from free public sources only. Writes data/indicators.json for the dashboard.

Sources:
  - EIA (US Energy Info Admin) — Brent crude price (free, no key needed)
  - RBA (Reserve Bank of Australia) — AUD/USD exchange rate
  - ACCC — retail fuel price monitoring page (scraped)
  - MarineTraffic public port calls (free tier, no key)
  - Baltic Exchange public indices via Freightos/Xeneta public data
  - Australian DISR — MSO stock data (published weekly as HTML table)
"""

import json
import os
import sys
import datetime
import urllib.request
import urllib.error
import re
import csv
import io

OUTPUT_FILE = "data/indicators.json"
_now  = datetime.datetime.now(datetime.timezone.utc)
TODAY = _now.strftime("%Y-%m-%d")
NOW_ISO = _now.strftime("%Y-%m-%dT%H:%M:%SZ")

def fetch_url(url, timeout=15):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (AGL-FuelDashboard/1.0; research)"
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")

# ── 1. Brent crude — EIA open data (no API key required) ─────────────────────
def fetch_brent():
    try:
        url = (
            "https://api.eia.gov/v2/petroleum/pri/spt/data/"
            "?api_key=DEMO_KEY"
            "&frequency=daily"
            "&data[0]=value"
            "&facets[series][]=RBRTE"
            "&sort[0][column]=period&sort[0][direction]=desc"
            "&length=5"
        )
        raw = fetch_url(url)
        d = json.loads(raw)
        rows = d.get("response", {}).get("data", [])
        if rows:
            val = float(rows[0]["value"])
            date = rows[0]["period"]
            return {"value": round(val, 2), "unit": "USD/bbl", "date": date, "source": "EIA"}
    except Exception as e:
        print(f"  [WARN] Brent EIA fetch failed: {e}")
    # Fallback — try Stooq CSV
    try:
        raw = fetch_url("https://stooq.com/q/d/l/?s=lco.f&i=d")
        rows = list(csv.reader(io.StringIO(raw)))
        if len(rows) >= 2:
            last = rows[-1]
            return {"value": round(float(last[4]), 2), "unit": "USD/bbl",
                    "date": last[0], "source": "Stooq"}
    except Exception as e:
        print(f"  [WARN] Brent Stooq fallback failed: {e}")
    return {"value": None, "unit": "USD/bbl", "date": TODAY, "source": "unavailable"}

# ── 2. AUD/USD — RBA statistical tables (free CSV) ───────────────────────────
def fetch_audusd():
    try:
        url = "https://www.rba.gov.au/statistics/tables/csv/f11-data.csv"
        raw = fetch_url(url)
        lines = raw.splitlines()
        # Find AUD/USD column (FXRUSD)
        header_idx = next((i for i, l in enumerate(lines) if "FXRUSD" in l), None)
        if header_idx is None:
            raise ValueError("FXRUSD column not found")
        # Data starts a few rows after headers
        data_lines = [l for l in lines[header_idx+4:] if l.strip() and l[0].isdigit()]
        if data_lines:
            last = data_lines[-1].split(",")
            # Date is first col, FXRUSD is in the column matching the header
            headers = lines[header_idx].split(",")
            col = next(i for i, h in enumerate(headers) if "FXRUSD" in h)
            val = float(last[col])
            date_str = last[0].strip()
            return {"value": round(val, 4), "unit": "AUD/USD", "date": date_str, "source": "RBA"}
    except Exception as e:
        print(f"  [WARN] RBA AUD/USD failed: {e}")
    # Fallback: exchangerate.host (free, no key)
    try:
        raw = fetch_url("https://api.exchangerate.host/latest?base=AUD&symbols=USD")
        d = json.loads(raw)
        val = d["rates"]["USD"]
        return {"value": round(val, 4), "unit": "AUD/USD", "date": TODAY, "source": "exchangerate.host"}
    except Exception as e:
        print(f"  [WARN] exchangerate.host fallback failed: {e}")
    return {"value": None, "unit": "AUD/USD", "date": TODAY, "source": "unavailable"}

# ── 3. ACCC national average unleaded petrol price ───────────────────────────
def fetch_accc_fuel():
    """
    ACCC publishes a weekly monitoring report. We scrape the summary table
    from their fuel monitoring page for the national average ULP price.
    """
    try:
        url = "https://www.accc.gov.au/consumers/petrol-and-fuel/petrol-prices-key-facts"
        html = fetch_url(url)
        # Look for a price pattern like 185.6 or 234.5 cents/litre in a prominent location
        matches = re.findall(r'(\d{2,3}\.\d)\s*cents?\s*(?:per|/)\s*litre', html, re.IGNORECASE)
        if matches:
            val = float(matches[0])
            return {"value": round(val, 1), "unit": "cents/litre", "date": TODAY,
                    "source": "ACCC", "note": "National avg ULP95"}
    except Exception as e:
        print(f"  [WARN] ACCC scrape failed: {e}")
    # Fallback: motormouth.com.au national average
    try:
        html = fetch_url("https://motormouth.com.au/")
        matches = re.findall(r'\$(\d+\.\d+)', html)
        if matches:
            val = float(matches[0]) * 100  # convert $/L to cents
            return {"value": round(val, 1), "unit": "cents/litre", "date": TODAY,
                    "source": "Motormouth", "note": "National avg ULP"}
    except Exception as e:
        print(f"  [WARN] Motormouth fallback failed: {e}")
    return {"value": None, "unit": "cents/litre", "date": TODAY, "source": "unavailable"}

# ── 4. DISR MSO stock data ────────────────────────────────────────────────────
def fetch_mso():
    """
    DISR publishes MSO compliance data at:
    https://www.energy.gov.au/government-priorities/energy-security/liquid-fuel-security
    We look for the most recent days-of-cover figures.
    """
    try:
        url = "https://www.energy.gov.au/government-priorities/energy-security/liquid-fuel-security"
        html = fetch_url(url)
        # Look for pattern like "XX days" near "diesel" or "petrol"
        diesel_match = re.search(
            r'diesel[^<]{0,80}?(\d{2,3})\s*days', html, re.IGNORECASE)
        petrol_match = re.search(
            r'petrol[^<]{0,80}?(\d{2,3})\s*days', html, re.IGNORECASE)
        diesel_days = int(diesel_match.group(1)) if diesel_match else None
        petrol_days = int(petrol_match.group(1)) if petrol_match else None
        if diesel_days or petrol_days:
            return {
                "diesel_days": diesel_days,
                "petrol_days": petrol_days,
                "date": TODAY,
                "source": "DISR"
            }
    except Exception as e:
        print(f"  [WARN] DISR MSO fetch failed: {e}")
    # If scraping fails, return null values — dashboard shows "check DISR manually"
    return {"diesel_days": None, "petrol_days": None, "date": TODAY, "source": "unavailable"}

# ── 5. Baltic Exchange BDI / dirty tanker proxy via public feed ──────────────
def fetch_freight():
    """
    Baltic Exchange data isn't fully free, but Freightos/Xeneta publish a
    weekly container rate index. For tanker rates we use a proxy via
    the IEA's published short-term energy outlook CSV which includes
    a tanker rate series, or fall back to a hardcoded "last known" sentinel.
    """
    try:
        # EIA STEO includes crude tanker rate series WTXCRUDE
        url = (
            "https://api.eia.gov/v2/steo/data/"
            "?api_key=DEMO_KEY"
            "&frequency=monthly"
            "&data[0]=value"
            "&facets[seriesId][]=WTXCRUDE"
            "&sort[0][column]=period&sort[0][direction]=desc"
            "&length=3"
        )
        raw = fetch_url(url)
        d = json.loads(raw)
        rows = d.get("response", {}).get("data", [])
        if rows:
            val = float(rows[0]["value"])
            return {"value": round(val, 1), "unit": "index", "date": rows[0]["period"],
                    "source": "EIA STEO", "note": "Crude tanker rate index (monthly)"}
    except Exception as e:
        print(f"  [WARN] EIA tanker rate fetch failed: {e}")
    return {"value": None, "unit": "index", "date": TODAY, "source": "unavailable",
            "note": "Baltic/Platts MR freight requires paid subscription"}

# ── 6. Hormuz transit proxy — port state via MarineTraffic public search ──────
def fetch_hormuz_proxy():
    """
    True AIS Hormuz transit counts require Kpler/MarineTraffic paid API.
    Free proxy: count of vessels recently reported at Fujairah (UAE) anchorage
    from MarineTraffic's public port page — a reasonable activity proxy.
    We return a qualitative status based on news signal rather than a live count.
    NOTE: For production, replace this with a Kpler or MT Professional API call.
    """
    # Without a paid API key we cannot get real-time AIS counts.
    # Return a sentinel that the dashboard renders as "manual update required"
    return {
        "value": None,
        "unit": "transits/day",
        "date": TODAY,
        "source": "manual",
        "note": "Requires MarineTraffic Professional or Kpler API for live count. Update manually from news sources."
    }

# ── 7. Singapore gasoil crack spread proxy ───────────────────────────────────
def fetch_crack_spread():
    """
    True Singapore crack spreads need Argus/Platts subscription.
    Proxy: derive an approximate crack from ICE gasoil futures vs Brent.
    ICE gasoil (GAS.F) is in USD/MT; convert to $/bbl (divide by 7.45).
    """
    try:
        gasoil_raw = fetch_url("https://stooq.com/q/d/l/?s=gas.f&i=d")
        gasoil_rows = list(csv.reader(io.StringIO(gasoil_raw)))
        brent_raw = fetch_url("https://stooq.com/q/d/l/?s=lco.f&i=d")
        brent_rows = list(csv.reader(io.StringIO(brent_raw)))
        if len(gasoil_rows) >= 2 and len(brent_rows) >= 2:
            gasoil_close = float(gasoil_rows[-1][4]) / 7.45  # USD/MT to USD/bbl
            brent_close  = float(brent_rows[-1][4])
            crack = gasoil_close - brent_close
            return {"value": round(crack, 2), "unit": "USD/bbl vs Brent",
                    "date": gasoil_rows[-1][0], "source": "ICE via Stooq",
                    "note": "ICE Gasoil proxy — not Singapore-specific"}
    except Exception as e:
        print(f"  [WARN] Crack spread calc failed: {e}")
    return {"value": None, "unit": "USD/bbl", "date": TODAY, "source": "unavailable",
            "note": "Singapore crack requires Argus/Platts subscription"}

# ── Threshold evaluation helpers ─────────────────────────────────────────────
def status(value, green_min, amber_min, invert=False):
    """
    Returns 'green'|'amber'|'red'|'unknown'.
    invert=True: higher is worse (e.g. Brent price, freight rates).
    """
    if value is None:
        return "unknown"
    if not invert:
        if value >= green_min:
            return "green"
        elif value >= amber_min:
            return "amber"
        else:
            return "red"
    else:
        if value <= green_min:
            return "green"
        elif value <= amber_min:
            return "amber"
        else:
            return "red"

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"[{NOW_ISO}] Fetching fuel early-warning indicators...")

    brent   = fetch_brent();    print(f"  Brent:        {brent}")
    audusd  = fetch_audusd();   print(f"  AUD/USD:      {audusd}")
    accc    = fetch_accc_fuel();print(f"  ACCC fuel:    {accc}")
    mso     = fetch_mso();      print(f"  MSO stocks:   {mso}")
    freight = fetch_freight();  print(f"  Freight idx:  {freight}")
    hormuz  = fetch_hormuz_proxy(); print(f"  Hormuz:       {hormuz}")
    crack   = fetch_crack_spread(); print(f"  Crack spread: {crack}")

    indicators = {
        "fetched_at": NOW_ISO,
        "data_date":  TODAY,
        "indicators": {
            "brent_crude": {
                **brent,
                "label": "Brent crude",
                "thresholds": {"green": 90, "amber": 120},
                "status": status(brent["value"], 90, 120, invert=True),
                "description": "Green <$90 · Amber $90–120 · Red >$120"
            },
            "audusd": {
                **audusd,
                "label": "AUD/USD",
                "thresholds": {"green": 0.66, "amber": 0.60},
                "status": status(audusd["value"], 0.66, 0.60),
                "description": "Green ≥0.66 · Amber 0.60–0.65 · Red <0.60"
            },
            "accc_fuel_price": {
                **accc,
                "label": "National avg ULP (c/L)",
                "thresholds": {"note": "No fixed threshold — monitor trend"},
                "status": "unknown" if accc["value"] is None else (
                    "red" if accc["value"] > 220 else
                    "amber" if accc["value"] > 180 else "green"
                ),
                "description": "Green <180 c/L · Amber 180–220 · Red >220"
            },
            "diesel_mso_days": {
                "value": mso["diesel_days"],
                "unit": "days cover",
                "date": mso["date"],
                "source": mso["source"],
                "label": "Diesel MSO cover",
                "thresholds": {"green": 40, "amber": 32},
                "status": status(mso["diesel_days"], 40, 32),
                "description": "Green >40 days · Amber 32–40 · Red <32 (legislative min)"
            },
            "petrol_mso_days": {
                "value": mso["petrol_days"],
                "unit": "days cover",
                "date": mso["date"],
                "source": mso["source"],
                "label": "Petrol MSO cover",
                "thresholds": {"green": 35, "amber": 27},
                "status": status(mso["petrol_days"], 35, 27),
                "description": "Green >35 days · Amber 27–35 · Red <27 (legislative min)"
            },
            "tanker_freight_index": {
                **freight,
                "label": "Crude tanker rate index",
                "thresholds": {"note": "EIA monthly proxy — not MR product tanker"},
                "status": "unknown" if freight["value"] is None else "amber",
                "description": "Proxy only — subscribe to Baltic Exchange for MR rates"
            },
            "hormuz_transits": {
                **hormuz,
                "label": "Hormuz tanker transits/day",
                "thresholds": {"green": 20, "amber": 10},
                "status": "unknown",
                "description": "Green ≥20/day · Amber 10–19 · Red <10 — requires paid AIS feed"
            },
            "gasoil_crack_spread": {
                **crack,
                "label": "Gasoil crack spread (proxy)",
                "thresholds": {"green": 25, "amber": 35},
                "status": status(crack["value"], 25, 35, invert=True) if crack["value"] else "unknown",
                "description": "Green <$25/bbl · Amber $25–35 · Red >$35 (physical tightening)"
            }
        },
        "composite": {
            "description": "Rationing risk: counts of red indicators firing",
            "red_count":   sum(1 for v in [] if v == "red"),  # computed below
            "risk_level":  "unknown"
        },
        "data_gaps": [
            "Hormuz AIS transits: requires MarineTraffic Professional or Kpler API",
            "Singapore-specific crack spreads: requires Argus or Platts subscription",
            "MR product tanker freight (Singapore-East AU): requires Baltic Exchange or Clarksons",
            "Independent retailer fill rate: requires HVIA/ATA industry feed",
            "AU-bound vessel departure count: requires Kpler/Vortexa",
            "ACCC fuel price: web scrape — may break if ACCC updates their page layout"
        ]
    }

    # Compute composite risk
    statuses = [v["status"] for v in indicators["indicators"].values()]
    red_count   = statuses.count("red")
    amber_count = statuses.count("amber")
    if red_count >= 3:
        risk = "CRITICAL"
    elif red_count >= 2 or (red_count == 1 and amber_count >= 2):
        risk = "HIGH"
    elif red_count >= 1 or amber_count >= 2:
        risk = "ELEVATED"
    else:
        risk = "NORMAL"

    indicators["composite"]["red_count"]   = red_count
    indicators["composite"]["amber_count"] = amber_count
    indicators["composite"]["risk_level"]  = risk

    os.makedirs("data", exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(indicators, f, indent=2)

    print(f"\n  Composite risk: {risk} ({red_count} red, {amber_count} amber)")
    print(f"  Written to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
