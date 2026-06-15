# Aircraft monitoring and notification

This explains how the skill watches an aircraft and alerts the analyst when a
condition is met, for example "watch N76528 and tell me when it gets within 100
miles of KAUS, check every 5 minutes." The data comes from the **live API**; the
scheduling is done with a **Claude Desktop scheduled task**. There is no separate
scheduler and no external email or webhook.

## The design: a single-shot check, not a loop

The monitor is **not** a long-running program. Each time the scheduled task fires,
the skill runs one quick check and exits:

1. Make **one** live API call for the target aircraft (by hex or registration).
2. Compute the great-circle distance from the aircraft to the airport (or evaluate
   whatever condition was set).
3. Read and update a small local **state file** in the case working folder (last
   status, and whether an alert already fired).
4. **Alert only once per condition transition.** The first run that finds the
   aircraft within range alerts; later runs that still find it within range stay
   quiet. If it leaves and comes back, that is a new transition.

The engine for steps 1 to 3 is
`${CLAUDE_PLUGIN_ROOT}/skills/adsbexchange-analyst/scripts/monitor.py`, which is
dependency-free and reads the API key from the credential store (see
`credentials.md`).

```bash
MON="${CLAUDE_PLUGIN_ROOT}/skills/adsbexchange-analyst/scripts/monitor.py"

# One check: alert if registration N76528 is within 100 nm of KAUS.
python3 "$MON" check \
    --registration N76528 \
    --airport KAUS \
    --within-nm 100 \
    --state ./monitors/N76528_KAUS.json
```

`monitor.py` prints a single line of JSON: the current status, the distance, and
whether this run is an alerting transition. The skill reads that and, on a
transition, tells the analyst.

## Trigger conditions the skill understands

- **within-nm** N of an airport (proximity, the common case).
- **on-ground at** an airport (landed: `alt_baro` is "ground" and within range).
- **departure detected** (was on the ground at the airport, now airborne).
- **altitude threshold** (above or below a given altitude).
- **speed threshold** (above or below a given ground speed).

The analyst describes the rule in plain language and the skill maps it to one of
these.

## Setting up the schedule in Claude Desktop

The skill guides the analyst to create a scheduled task that runs the check on their
cadence. Scheduled tasks inherit the analyst's plugins and connected tools, so the
task can re-invoke this very skill on a schedule.

- For everyday use, point them at **Cowork scheduled tasks** (plain-language setup,
  no code, available on paid plans).
- Five minutes and other off-grid intervals are not in the schedule picker, so have
  the analyst describe the cadence in plain words, for example "run my N76528
  monitor every 5 minutes." That is how Claude sets a non-standard interval.
- The task's delivered output **is** the alert. Claude Desktop surfaces it. Do not
  add any external email or webhook dispatch.

## Two limitations to state plainly

**Local tasks only run while the computer is awake and Claude Desktop is open.**
A local scheduled task is skipped if the machine is asleep or the app is closed,
and a missed run is not retried until the machine wakes or the app reopens. For a
flight monitor that matters, so say it plainly.

**Remote (cloud) routine for always-on monitoring.** If the analyst needs the
monitor to fire even when their computer is off, explain the remote routine option
that runs in Anthropic's cloud. Its one catch, in plain terms: a cloud run cannot
read the API key from the local keychain, so the key has to be available to that
remote context (for example as the `ADSBX_API_KEY` environment variable in the
routine). See `credentials.md`.

## Respect the request budget

The base live plan is about 10,000 requests per month. A continuous 5-minute check
is roughly 8,600 requests per month, which is close to the cap for a single monitor.
Warn the analyst plainly if their cadence and duration would exceed it, and suggest
a gentler interval. Rough monthly counts:

| Interval | Checks per month | Note |
| --- | --- | --- |
| every 5 min | ~8,640 | near the ~10,000 cap for one monitor |
| every 10 min | ~4,320 | comfortable |
| every 15 min | ~2,880 | comfortable |
| every 30 min | ~1,440 | light |
| every hour | ~720 | very light |

`monitor.py` accepts `--interval-min` purely so it can warn when a cadence would
blow the budget; it does not schedule anything itself.

## Stopping and listing monitors

A monitor is just a scheduled task, so:

- **List active monitors** maps to listing the analyst's scheduled tasks.
- **Stop a monitor** maps to pausing or deleting that scheduled task.

Tell the analyst the plain steps in Claude Desktop (open scheduled tasks, find the
named monitor, pause or delete it). Deleting the task stops the checks; the small
state file can be left in place or removed.

## If no key is stored

The monitor needs a live key. If none is found, do not fall back silently. Tell the
analyst a key is needed, offer the signup walk-through, and offer a one-time
globe-UI spot check in the meantime, with a clear note that continuous checking of
the website is discouraged. See `credentials.md`.
