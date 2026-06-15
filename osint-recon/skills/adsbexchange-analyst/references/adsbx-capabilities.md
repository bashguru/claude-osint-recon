# ADS-B Exchange capabilities (verified reference)

This is the detailed reference behind the **adsbexchange-analyst** skill. The
machine-readable version (the one the self-heal loop reads and repairs) lives at
`${CLAUDE_PLUGIN_ROOT}/skills/adsbexchange-analyst/data/adsbx_map.json`. This file
explains the same facts in prose for a human reader.

Everything below was confirmed against the live site and the official docs on
**2026-06-15**. The site changes, so treat anything marked "documented" or
"inferred" as needing a quick live check, and let the self-heal loop correct the
JSON map when something drifts.

A plain-language reminder that the skill repeats to the analyst: **all dates and
times on ADS-B Exchange are UTC** (also written "Z" for Zulu, a single world clock).
The skill converts the analyst's local date for them.

## The three data surfaces (route to the right one)

ADS-B Exchange exposes three separate ways to get data. They are not
interchangeable, so the skill picks one per task.

1. **Globe UI** (`https://globe.adsbexchange.com/`, a tar1090 map). Free, no
   account. This is the **default for historical work**, for snapshot evidence,
   and for KML. It is a human-driven web page, not something to scrape at volume.
2. **Live API** ("API Lite" / "Personal Use Aircraft Data API," via RapidAPI).
   Live last-known position only, no date. This is the surface for **live tracking
   and the monitor/notify loop**. About 10 USD per month, roughly 10,000 requests,
   no standard free tier.
3. **Historical trace archive** (S3 / Cloudflare R2). Date-addressable daily files
   for **older or bulk** history. An opt-in paid upgrade with an annual commitment,
   plus a free public sample bucket for testing.

Routing rule the skill follows:

- **Live track / monitor / notify** uses the **live API** (date is not needed for
  "live"), and falls back to the globe UI if no key is set up.
- **Historical departure pull** defaults to the **free globe UI**, which does the
  UTC date picker and KML natively. The **trace archive** is used only if the
  analyst opts into that upgrade for older or bulk data.

## Surface 1: the globe UI

### Deep-link URL parameters

Prepend `?` before the first parameter and `&` before each additional one.
Parameters are not case sensitive. Some take a value, some are flags.

| Parameter | Effect | Verified |
| --- | --- | --- |
| `icao=A4400F` | Center, select, and isolate one aircraft by ICAO hex | live |
| `airport=KAUS` | Center the map on an airport (ICAO code) | live |
| `showTrace=YYYY-MM-DD` | Load the historical track for the selected aircraft on that UTC day | live |
| `zoom=1-20`, `lat=`, `lon=` | Framing | live |
| `icaoFilter=hex1,hex2` | Show only the listed aircraft | documented |
| `replay` | Activate the replay toolbar (flag) | documented |
| `tempTrails=NN` | Temporary trails for NN seconds of recent history | documented |
| `SiteLat=`, `SiteLon=` | Set the viewer location for range rings | documented |
| `heatmap=NN`, `heatDuration=H`, `heatEnd=H` | History-dot density and window | documented |
| `mil` | Military / interesting filter (flag) | documented |
| `kiosk`, `hideSidebar`, `hideButtons` | Hide chrome and ads for clean snapshots | documented |
| `largeMode=1-4`, `monochromeMarkers=hex`, `monochromeTracks=hex`, `mapDim` | Legibility | documented |
| `reset`, `showerrors` | Reset settings / surface errors (troubleshooting and self-heal) | documented |

The `showTrace=YYYY-MM-DD` parameter is the important one for historical work. It is
the deep-link the UI itself sets when you click **History**, so you can frame a
historical day deterministically with a URL and then click only where needed.

Keyboard and button shortcuts worth knowing: `U` military/interesting, `T` tracks,
`K` track labels and trackpoints, `L` labels, `F` follow, `I` isolate, `M`
multiselect, `P` persistence, `H` home/reset, `Shift+L` estimated last leg vs full
trace, `Shift+S` hide buttons.

### Interactive history and KML flow (the click-through)

The right sidebar (Search tab) has **two separate boxes** that do different jobs:

- **"Search:"** (`#search_input`) finds an aircraft by callsign, registration, or
  hex.
- **"Jump to Airport or Latitude, Longitude:"** (`#jump_input`, with a **Jump**
  button) frames the map on an airport like KAUS.

The flow, with the verified selectors:

1. Optionally **Jump** to the departure airport (`#jump_input` then the Jump
   button) to frame the view.
2. Enter the flight number (callsign), tail number (registration), or hex in
   **Search:** (`#search_input`) and submit. The aircraft pane
   (`#selected_infoblock`) opens on the left, showing the callsign
   (`#selected_callsign`), **Hex** with a **Copy Link** permalink
   (`#selected_icao` and the Copy Link anchor), **Reg.** (`#selected_registration`),
   **Type** (`#selected_icaotype`), **Type Desc.** (`#selected_typedesc`),
   **Squawk** (`#selected_squawk1`), a **DB flags** line, plus **FULL DETAILS**
   (`#show_detail`) and **FLIGHT ACTIVITY**.
3. Click **History** (`#show_trace`). This loads the day's track and sets
   `showTrace=YYYY-MM-DD`. Set the **"UTC day:"** field (`#histDatePicker`) to the
   target date, or step it with **previous / next** (`#trace_back_1d` /
   `#trace_jump_1d`).
4. Use the **Legs previous / next** buttons (`#leg_prev` / `#leg_next`) to step to
   the specific leg that departs the airport in question. A "leg" is one
   takeoff-to-landing segment.
5. To replay, **click the trace line on the map** to start playback, then use the
   speed controls (`#tStop`, `#t1x`, `#t5x`, `#t10x`, `#t20x`, `#t40x`) and read the
   "Time: HH:MM:SS Z" field. Press **`K`** to show **trackpoints**; clicking a
   trackpoint updates the left-column data (altitude, speed, autopilot settings).
6. Record the **Copy Link** permalink for the case file. Its href is the shareable
   globe URL for this aircraft.

### KML export (verified)

The three KML buttons appear in the left pane once a historical track is loaded.
Each one generates a Google Earth KML through a
`data:application/vnd.google-earth.kml+xml` download.

| Button id | Label | Downloads | Use |
| --- | --- | --- | --- |
| `#export_kml_geom_avg` | "baro + avg.(EGM96 - baro)" | `<REG>-track-EGM96_avg.kml` | **Default.** Terrain-aligned, saved by default. Verified live. |
| `#export_kml_geom` | "geometric altitude (EGM96)" | `<REG>-track-EGM96.kml` | Geometric (GNSS) altitude. |
| `#export_kml_baro` | "uncorrected pressure alt." | `<REG>-track-baro.kml` | Uncorrected barometric altitude. |

The `baro + avg` button was confirmed live: clicking it produced
`N373MM-track-EGM96_avg.kml`. A KML opens the 3D flight path in Google Earth (and
loads into tools like FlySto).

### How far back history goes

History depends on data retention. If a requested UTC day returns no track, the
skill says so plainly rather than retrying blindly. For older or bulk data, the
trace archive (surface 3) is the right tool.

## Surface 2: the live API (for live tracking and the monitor)

- **Base URL:** `https://gateway.adsbexchange.com/api/aircraft/v2/{selector}/{value}`
- **Auth header (direct):** `api-auth: YOUR_API_KEY`
- **Auth headers (RapidAPI):** `x-rapidapi-key: YOUR_API_KEY` and
  `x-rapidapi-host: adsbexchange-com1.p.rapidapi.com`
- **Docs:** the ReDoc/Swagger page at
  `https://gateway.adsbexchange.com/api/aircraft/v2/docs/index.html?url=/api/aircraft/v2/docs/openapi.json`
- **Sample call:** `https://www.adsbexchange.com/data-products/sample-api-call/`

Selectors confirmed in the live OpenAPI spec:

| Path | Returns |
| --- | --- |
| `/hex/{hex}` | Last known position by ICAO hex |
| `/icao/{icao}` | Aircraft by ICAO hex (comma-separate for several) |
| `/registration/{registration}` | Aircraft by registration (tail number) |
| `/callsign/{callsign}` | Aircraft by callsign |
| `/sqk/{squawk}` | Aircraft by squawk |
| `/lat/{lat}/lon/{lon}/dist/{dist}` | Aircraft within {dist} nautical miles of a point |
| `/airport/{airport}` | Aircraft near an airport |
| `/mil` | Military aircraft |

**Response shape.** The gateway v2 response is a wrapper object:

```
{ "ac": [ {aircraft...}, ... ], "msg": "No error", "now": 1675633671226, "total": 1, "ctime": ..., "ptime": ... }
```

Parse the **`ac`** array. Older field docs call it `aircraft`; the gateway uses
`ac`. Useful per-aircraft fields: `hex`, `flight` (callsign, may be space-padded),
`r` (registration), `t` (type), `lat`, `lon`, `alt_baro`, `gs` (ground speed kt),
`track`, `squawk`, `nav_modes`, `seen` (seconds since last message), and `dbFlags`
(bitfield: military=1, interesting=2, PIA=4, LADD=8).

**Quirks and client guidance.**

- Requesting a single aircraft by ICAO returns a single object for backward
  compatibility. Append a trailing comma to the hex to force a collection
  response.
- Send `Accept-Encoding: gzip`, access values by name (do not hard-code JSON
  property order), and tolerate new additive fields.
- This surface is **live only**. There is no date parameter. Do not try to get
  historical tracks here.

**Cost.** "API Lite" / "Personal Use Aircraft Data API" is sold through RapidAPI
(`https://rapidapi.com/adsbx/api/adsbexchange-com1/`). About 10 USD per month for
roughly 10,000 requests, no standard free tier (a data feeder may get the fee
waived). The Enterprise API is the commercial tier. Verify current pricing on
RapidAPI, since it changes.

## Surface 3: the historical trace archive (opt-in upgrade)

Date-addressable daily trace files over an Amazon S3-compatible API (Cloudflare
R2). Full access is a paid subscription with an annual commitment. Offer this only
when the analyst needs older or bulk archived data beyond what the free globe shows.

- **Endpoint:** `https://6ff2cd7dae70306649e2c1e1500e2e0a.r2.cloudflarestorage.com/`
- **Tools:** rclone or aws-cli.
- **Free testing path:** the public **`adsbx-sample-data`** bucket, open to
  everyone with ADS-B Exchange's published sample credentials (see
  `pull-data/` and the JSON map). Layout example:
  `readsb-hist/YYYY/MM/DD/HHMMSSZ.json.gz`. There is also a documented
  `https://samples.adsbexchange.com/hires-traces/YYYY/MM/DD/` path; confirm it live
  before relying on it.
- **Recent buckets** (about the last 90 days, real time): `adsbx-recent-traces`,
  `adsbx-recent-hires-traces`, `adsbx-recent-readsb-hist`.
- **Yearly buckets** (older): `adsbx-YYYY-traces`, `adsbx-YYYY-hires-traces`,
  `adsbx-YYYY-readsb-hist`.
- **Trace file format:** `{ icao, timestamp, trace: [ [secondsAfterTimestamp, lat,
  lon, altitude, groundspeed, track, flags, verticalRate, details, ...], ... ] }`.
  The `flags` bitfield bit 2 (`flags & 2`) marks the start of a new leg, which is how
  the skill separates one flight from the next in a day.
- **Aircraft database** for hex-to-registration:
  `https://downloads.adsbexchange.com/downloads/basic-ac-db.json.gz`.
- **Pull-data docs:** `https://www.adsbexchange.com/pull-data/`.

## Anti-bot reality on the globe

- The globe is protected by **Google reCAPTCHA** (the invisible, score-based kind;
  the `g-recaptcha-response` field is present on the page). It only shows a puzzle
  if behavior looks robotic. During human-paced interaction on 2026-06-15 no puzzle
  appeared. The skill never solves or bypasses it; it applies the run's bot policy.
- A separate **BounceX marketing email-capture popup** (`#bx-campaign-...`) can
  appear and intercept clicks. That is a newsletter overlay, **not** a bot
  challenge, so the skill dismisses it (`#bx-close-inside-...`) and continues.
- The page carries a heavy ad and tracking stack. For clean court snapshots, use
  the `kiosk` / `hideSidebar` / `hideButtons` parameters and dismiss the popup.

## Terms of use (state this plainly)

ADS-B Exchange data is licensed for **personal or non-profit research, non-profit
education, or internal testing and evaluation**. Commercial use requires written
permission from ADS-B Exchange. Publications must cite "ADSBexchange,
http://www.ADSBexchange.com". Respect `robots.txt`, throttle, and back off on `403`
or `429`. For anything repeated or programmatic, use the official API or the trace
archive rather than the globe.

- Terms of Use: `https://www.adsbexchange.com/terms-of-use-011425/`
- Acceptable Use Policy: `https://www.adsbexchange.com/acceptable-use-policy/`
