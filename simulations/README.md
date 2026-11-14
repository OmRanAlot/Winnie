# Winnie impact simulations

Estimates of how much time Winnie would have saved the WiCS e-board on the **real Fall 2026 task
tracker** (126 tasks, Aug–Dec 2026). **The time numbers are simulated, not measured**: the tracker
records deadlines, not how long each task took. Each task gets a real-world estimate from its
category. Each Winnie feature changes only the part of the work it touches. 2,000 Monte Carlo
semesters (fixed seed, reproducible) turn the assumptions into ranges.

```bash
uv run simulations/simulate.py        # regenerates data/winnie_simulation.csv, data/summary.csv, charts/
```

## Files

| File | What |
|---|---|
| `data/tracker_tasks.csv` | The real tracker with **roles instead of people**: no emails or names |
| `data/winnie_simulation.csv` | Per task: expected hours, days to done, days late and on-time odds, without vs with Winnie, plus which Winnie features apply |
| `data/summary.csv` | Headline numbers: median and 90% range across the 2,000 runs |
| `charts/01–06_*.png` | Presentation charts |
| `simulate.py` | The model. Every assumption is a named constant at the top |
| `prepare_tasks.py` | Rebuilds `tracker_tasks.csv` from a raw tracker export (maps emails and names to roles) |

## Headline results (median, 90% range)

| | Without Winnie | With Winnie |
|---|---|---|
| Board hours on these 124 tasks | 556 h (530–585) | 339 h (319–361) |
| Coordination hours (chasing, status pings, tracking) | 262 h | 81 h |
| Tasks finished on time (within a day) | 68% | 92% |
| Late tasks | 40 | 10 |
| Average days from assigned to done | 6.7 | 4.9 |

That's about **217 board hours saved per semester (~39%)**, or roughly 18 hours per member.

## How it's modelled

Each task is split into **hands-on work** and **coordination** (asking who has it, chasing replies,
finding details in Docs or Discord, updating the tracker), plus **calendar time** and the
**risk of slipping**. The baselines per category are in `CATEGORIES` in `simulate.py`, e.g. room
booking 0.5 h of work + 1 h of coordination; flyers 3 h + 1.5 h.

| Winnie feature | What it changes in the model |
|---|---|
| Meeting capture (tasks pulled from meetings) | Chance a task never reaches the tracker drops from 25% to 3%, so tasks don't start days late |
| One source of truth + targeted notifications | Coordination time falls 60–75%; tracking overhead falls from 15 to 3 minutes per task |
| Dependency alerts | Mean wait on another role falls from 2 days to 0.5 days (e.g. purchase list → Treasurer) |
| Deadline reminders over iMessage | Chance of a slip falls ~60%; slips that do happen are half as long |
| AI drafts (emails, recaps, posts, listings, slide outlines) | Hands-on time for writing tasks falls ~35% |
| Skill-matched reassignment | 60% of the overload in a member's busy week moves to the three lightest members |

Excluded: the 2 tasks owned by external candidates. "Whole board" tasks count 12 people.

**Use the numbers honestly in the pitch.** Say "simulated on our real task tracker", and quote the
ranges, not just the medians. To test a more or less optimistic case, change the constants at the
top of `simulate.py` and rerun.
