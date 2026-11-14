# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib>=3.8", "numpy>=1.26"]
# ///
"""Simulated impact of Winnie on the Fall 2026 WiCS task tracker (126 real tasks).

ALL TIME NUMBERS ARE ESTIMATES. The tracker records deadlines, not how long work took, so each task
gets a real-world estimate from its category (hands-on hours, coordination hours, calendar days),
and each Winnie feature changes only the part of the work it touches. 2,000 Monte Carlo semesters
(fixed seed, reproducible) turn those assumptions into ranges instead of single guesses.

    uv run simulations/simulate.py

Reads data/tracker_tasks.csv (made by prepare_tasks.py) and writes:
    data/winnie_simulation.csv   per task: expected hours, days, on-time odds, without vs with Winnie
    data/summary.csv             headline numbers with 90% ranges
    charts/*.png                 presentation charts
"""

import csv
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
TASKS_CSV = HERE / "data" / "tracker_tasks.csv"
RUNS = 2000
SEED = 2026
BOARD_SIZE = 12

# ---------------------------------------------------------------------------------------------
# Real-world estimates per task category (median values for one owner, before Winnie).
#   work   hands-on hours doing the task itself
#   coord  hours of coordination around it: asking who has it, chasing replies, status pings,
#          finding the doc/Discord thread with the details, updating the tracker
#   days   calendar days from "assigned" to "done" when nothing goes wrong
#   handoff  needs something from another role first (room before listing, list before order...)
#   draft    Winnie can produce a first draft (email, recap, post, listing text, slide outline)
# Order matters: the first matching pattern wins.
# ---------------------------------------------------------------------------------------------
CATEGORIES = [
    # name                     pattern                                                    work coord days handoff draft
    ("Room booking",           r"room booked|book rooms",                                  0.5, 1.0, 2, False, False),
    ("Purchasing & orders",    r"amazon|order|supplies|purchase|goodie",                   1.5, 2.0, 4, True,  False),
    ("Event listings",         r"highlander|discord event",                                0.75, 0.75, 2, True, True),
    ("Flyers, reels & social", r"flyer|reel|marketing|instagram|infographic",              3.0, 1.5, 5, False, False),
    ("Slides",                 r"slides",                                                  3.0, 1.5, 4, True,  True),
    ("Opportunity posts",      r"post opportunities",                                      0.75, 0.5, 2, False, True),
    ("Recaps & newsletters",   r"recap|reflection|newsletter|write up",                    2.5, 1.0, 5, False, True),
    ("Emails & outreach",      r"email|reach out|message|reminder|thank you|follow up|send|proposal|parking",
                                                                                           1.0, 1.25, 3, False, True),
    ("Elections",              r"interview|candidate|election|deliberation|shortlist|reapplication|onboarding|decision",
                                                                                           3.0, 2.5, 6, True,  False),
    ("Web & internal tools",   r"website|drive|spreadsheet|google form|credentials|gcal",  3.0, 1.0, 5, False, False),
    ("Planning & logistics",   r".",                                                       2.5, 2.5, 6, True,  False),
]

# ---------------------------------------------------------------------------------------------
# What each Winnie feature changes (the "with Winnie" side). Conservative on purpose.
# ---------------------------------------------------------------------------------------------
TRACKING_OVERHEAD_H = 0.25        # per task: copying it into the tracker, finding it again later
TRACKING_WITH_WINNIE_H = 0.05     # check it off by iMessage DM; meeting capture logs it
COORD_KEPT = (0.25, 0.40)         # one source of truth + targeted notifications: 60-75% less chasing
DRAFT_WORK_KEPT = 0.65            # AI first drafts cut writing tasks' hands-on time by ~35%
OTHER_WORK_KEPT = 0.95            # details are attached to the task: ~5% less searching
P_NOT_LOGGED = (0.25, 0.03)       # task said in a meeting but never reached the tracker (Cluely-style capture)
NOT_LOGGED_DELAY_DAYS = (1, 4)    # ...so it starts late by this many days
HANDOFF_WAIT_DAYS = (2.0, 0.5)    # mean wait on another role; dependency alerts fire when it unblocks
HANDOFF_SLACK_DAYS = 3            # waiting longer than this eats into the deadline
P_SLIP = {"High": (0.15, 0.06), "Normal": (0.22, 0.09), "Low": (0.30, 0.12)}  # deadline reminders
SLIP_DAYS_MEDIAN = (3.0, 1.5)     # reminders + skill-matched reassignment shorten slips
REASSIGN_ACCEPTED = 0.6           # share of an overloaded week Winnie's suggestions move to lighter members

# Colors: validated reference palette (dataviz skill), slots 1-2; ink and surface tokens.
WITH, WITHOUT = "#2a78d6", "#eb6834"
INK, INK_2, INK_3, GRID, SURFACE = "#0b0b0b", "#52514e", "#8a8984", "#e4e3df", "#fcfcfb"


def load_tasks():
    with TASKS_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    tasks = []
    for r in rows:
        if r["assignee_roles"] == "External":
            continue  # candidates' deadlines, not board work
        for name, pattern, work, coord, days, handoff, draft in CATEGORIES:
            if re.search(pattern, r["task"], re.I):
                break
        whole_board = r["assignee_roles"] == "Whole board"
        roles = [x.strip() for x in r["assignee_roles"].split(";")]
        tasks.append({**r, "category": name, "work": work * (BOARD_SIZE * 0.4 if whole_board else 1),
                      "coord": coord, "days": days, "handoff": handoff, "draft": draft,
                      "roles": roles, "n": BOARD_SIZE if whole_board else max(1, int(r["n_assignees"])),
                      "deadline": date.fromisoformat(r["deadline"])})
    return tasks


def simulate(tasks, rng):
    """Arrays of shape (RUNS, tasks) for each measure, without (0) and with (1) Winnie."""
    k = len(tasks)
    n = np.array([t["n"] for t in tasks], float)
    team = 1 + 0.15 * (np.minimum(n, 4) - 1)               # more owners: a bit more total effort
    team_coord = 1 + 0.35 * (np.minimum(n, 4) - 1)          # ...and a lot more coordination
    work0 = np.array([t["work"] for t in tasks]) * team * rng.lognormal(0, 0.35, (RUNS, k))
    coord0 = np.array([t["coord"] for t in tasks]) * team_coord * rng.lognormal(0, 0.4, (RUNS, k))
    coord0 += TRACKING_OVERHEAD_H
    kept = np.where([t["draft"] for t in tasks], DRAFT_WORK_KEPT, OTHER_WORK_KEPT)
    work1 = work0 * kept * rng.uniform(0.9, 1.1, (RUNS, k))
    coord1 = (coord0 - TRACKING_OVERHEAD_H) * rng.uniform(*COORD_KEPT, (RUNS, k)) + TRACKING_WITH_WINNIE_H

    base_days = np.array([t["days"] for t in tasks]) * rng.lognormal(0, 0.3, (RUNS, k))
    handoff = np.array([t["handoff"] for t in tasks])
    slip_p = np.array([[P_SLIP.get(t["priority"], P_SLIP["Normal"])[i] for t in tasks] for i in (0, 1)])
    out = {}
    for i in (0, 1):
        not_logged = rng.random((RUNS, k)) < P_NOT_LOGGED[i]
        start_delay = not_logged * rng.uniform(*NOT_LOGGED_DELAY_DAYS, (RUNS, k))
        wait = handoff * rng.exponential(HANDOFF_WAIT_DAYS[i], (RUNS, k))
        slipped = rng.random((RUNS, k)) < slip_p[i]
        slip = slipped * rng.lognormal(np.log(SLIP_DAYS_MEDIAN[i]), 0.5, (RUNS, k))
        late = slip + np.maximum(0, wait - HANDOFF_SLACK_DAYS) + np.maximum(0, start_delay - 2)
        out[i] = {"work": (work0, work1)[i], "coord": (coord0, coord1)[i],
                  "cycle": base_days + start_delay + wait + slip, "late": late}
        out[i]["hours"] = out[i]["work"] + out[i]["coord"]
    return out


def weekly_role_load(tasks, hours):
    """{role: {week monday: hours}} from one run's per-task hours, split evenly between owners."""
    load = defaultdict(lambda: defaultdict(float))
    for t, h in zip(tasks, hours):
        roles = [r for r in t["roles"] if r not in {"Unassigned", "Whole board"}]
        week = t["deadline"] - timedelta(days=t["deadline"].weekday())
        for r in roles:
            load[r][week] += h / len(roles)
    return load


def rebalance(load):
    """Winnie suggests skill-matched substitutes when one member's week is far above the board's."""
    weeks = sorted({w for r in load.values() for w in r})
    roles = sorted(load)
    out = {r: dict(load[r]) for r in roles}
    for w in weeks:
        vals = {r: out[r].get(w, 0.0) for r in roles}
        cap = max(4.0, 1.5 * np.mean(list(vals.values())))
        for r, v in sorted(vals.items(), key=lambda x: -x[1]):
            excess = (v - cap) * REASSIGN_ACCEPTED
            if excess <= 0:
                continue
            out[r][w] = v - excess
            light = sorted(roles, key=lambda x: out[x].get(w, 0.0))[:3]  # three lightest members share it
            for lr in light:
                out[lr][w] = out[lr].get(w, 0.0) + excess / 3
    return out


def style(ax, title, subtitle=None, xgrid=False):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK_2, length=0, labelsize=10)
    ax.grid(axis="x" if xgrid else "y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_title(title, loc="left", fontsize=15, fontweight="bold", color=INK, pad=28 if subtitle else 12)
    if subtitle:
        ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=10.5, color=INK_2, va="bottom")


def legend(ax, loc="upper right"):
    leg = ax.legend(frameon=False, fontsize=10, loc=loc, labelcolor=INK_2)
    return leg


def save(fig, name):
    fig.text(0.01, 0.01, "Simulated estimates · 124 board tasks from the Fall 2026 tracker · 2,000 Monte Carlo runs",
             fontsize=8.5, color=INK_3)
    fig.savefig(HERE / "charts" / name, dpi=200, facecolor=SURFACE, bbox_inches="tight", pad_inches=0.3)
    plt.close(fig)


def main():
    tasks = load_tasks()
    rng = np.random.default_rng(SEED)
    sim = simulate(tasks, rng)
    (HERE / "charts").mkdir(exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "figure.facecolor": SURFACE})

    # ---- per-task CSV (expected values across runs) -----------------------------------------
    features = {
        "Room booking": "meeting capture; dependency alert to listings and flyers",
        "Purchasing & orders": "dependency alert (purchase list -> Treasurer); deadline reminder",
        "Event listings": "AI draft from event details; alert when room and flyer are ready",
        "Flyers, reels & social": "meeting capture; targeted done-notification; skill-matched help",
        "Slides": "AI outline; alert when theme is decided",
        "Opportunity posts": "AI draft; DM reminder and check-off",
        "Recaps & newsletters": "AI draft from meeting transcript; DM check-off",
        "Emails & outreach": "AI draft; shared-inbox triage and follow-up reminder",
        "Elections": "dependency tracking; targeted notifications; reminders",
        "Web & internal tools": "one source of truth; deadline reminder",
        "Planning & logistics": "meeting capture; dependency tracking; reassignment suggestions",
    }
    rows = []
    for j, t in enumerate(tasks):
        w0, w1 = sim[0], sim[1]
        rows.append({
            "task_id": t["task_id"], "event": t["event"], "task": t["task"], "category": t["category"],
            "priority": t["priority"], "status": t["status"], "assignee_roles": t["assignee_roles"],
            "deadline": t["deadline"].isoformat(),
            "work_hours_without": round(w0["work"][:, j].mean(), 2),
            "coordination_hours_without": round(w0["coord"][:, j].mean(), 2),
            "total_hours_without": round(w0["hours"][:, j].mean(), 2),
            "work_hours_with_winnie": round(w1["work"][:, j].mean(), 2),
            "coordination_hours_with_winnie": round(w1["coord"][:, j].mean(), 2),
            "total_hours_with_winnie": round(w1["hours"][:, j].mean(), 2),
            "hours_saved": round((w0["hours"][:, j] - w1["hours"][:, j]).mean(), 2),
            "pct_time_saved": round(100 * (1 - w1["hours"][:, j].mean() / w0["hours"][:, j].mean()), 1),
            "days_to_done_without": round(w0["cycle"][:, j].mean(), 1),
            "days_to_done_with_winnie": round(w1["cycle"][:, j].mean(), 1),
            "avg_days_late_without": round(w0["late"][:, j].mean(), 2),
            "avg_days_late_with_winnie": round(w1["late"][:, j].mean(), 2),
            "on_time_prob_without": round((w0["late"][:, j] < 1).mean(), 3),
            "on_time_prob_with_winnie": round((w1["late"][:, j] < 1).mean(), 3),
            "winnie_features": features[t["category"]],
            "data_type": "simulated estimate",
        })
    with (HERE / "data" / "winnie_simulation.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    # ---- headline numbers ---------------------------------------------------------------------
    def band(x):
        return np.percentile(x, [50, 5, 95])

    tot0, tot1 = sim[0]["hours"].sum(1), sim[1]["hours"].sum(1)
    coord0, coord1 = sim[0]["coord"].sum(1), sim[1]["coord"].sum(1)
    ontime0, ontime1 = (sim[0]["late"] < 1).mean(1) * 100, (sim[1]["late"] < 1).mean(1) * 100
    late0, late1 = (sim[0]["late"] >= 1).sum(1), (sim[1]["late"] >= 1).sum(1)
    cyc0, cyc1 = sim[0]["cycle"].mean(1), sim[1]["cycle"].mean(1)
    summary = [
        ("Board hours on these tasks, without Winnie", band(tot0)),
        ("Board hours on these tasks, with Winnie", band(tot1)),
        ("Board hours saved", band(tot0 - tot1)),
        ("Percent of hours saved", band(100 * (1 - tot1 / tot0))),
        ("Coordination hours (chasing, status, tracking), without", band(coord0)),
        ("Coordination hours, with Winnie", band(coord1)),
        ("Tasks done on time (%), without", band(ontime0)),
        ("Tasks done on time (%), with Winnie", band(ontime1)),
        ("Late tasks, without", band(late0)),
        ("Late tasks, with Winnie", band(late1)),
        ("Average days from assigned to done, without", band(cyc0)),
        ("Average days from assigned to done, with Winnie", band(cyc1)),
    ]
    with (HERE / "data" / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "median", "low_5pct", "high_95pct"])
        for name, (m, lo, hi) in summary:
            writer.writerow([name, round(m, 1), round(lo, 1), round(hi, 1)])
            print(f"{name:58s} {m:7.1f}   (90% range {lo:.1f}-{hi:.1f})")

    # ---- chart 1: hours by category ------------------------------------------------------------
    cats = defaultdict(lambda: [0.0, 0.0])
    for r in rows:
        cats[r["category"]][0] += r["total_hours_without"]
        cats[r["category"]][1] += r["total_hours_with_winnie"]
    order = sorted(cats, key=lambda c: cats[c][0])
    y = np.arange(len(order))
    fig, ax = plt.subplots(figsize=(11, 6.5))
    h = 0.36
    ax.barh(y + h / 2 + 0.01, [cats[c][0] for c in order], h, color=WITHOUT, label="Without Winnie")
    ax.barh(y - h / 2 - 0.01, [cats[c][1] for c in order], h, color=WITH, label="With Winnie")
    for i, c in enumerate(order):
        a, b = cats[c]
        ax.text(a + 1.5, i + h / 2, f"−{100 * (1 - b / a):.0f}%", va="center", fontsize=9.5, color=INK_2)
    ax.set_yticks(y, order, color=INK)
    ax.set_xlabel("Board hours (all tasks in the category)", color=INK_2)
    style(ax, "Where Winnie saves the most time",
          "Expected hands-on + coordination hours per task category, Fall 2026 tracker", xgrid=True)
    legend(ax, "lower right")
    save(fig, "01_hours_by_category.png")

    # ---- chart 2: Monte Carlo distribution of hours saved -------------------------------------
    saved = tot0 - tot1
    m, lo, hi = band(saved)
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.hist(saved, bins=45, color=WITH, edgecolor=SURFACE, linewidth=1.2)
    ax.axvspan(lo, hi, color=WITH, alpha=0.08, zorder=0)
    ax.axvline(m, color=INK, linewidth=1.5)
    ax.text(m, ax.get_ylim()[1] * 0.97, f"  median {m:.0f} hours saved", color=INK, fontsize=11, va="top")
    ax.text(lo, ax.get_ylim()[1] * 0.6, f"90% of runs: {lo:.0f}–{hi:.0f} h  ", color=INK_2, fontsize=10,
            va="top", ha="right")
    ax.set_xlabel("Board hours saved in one semester", color=INK_2)
    ax.set_ylabel("Simulated semesters", color=INK_2)
    style(ax, f"Winnie saves ~{m:.0f} board hours a semester",
          f"2,000 simulated semesters of the same 124 board tasks · about {m / BOARD_SIZE:.0f} hours per member")
    save(fig, "02_hours_saved_monte_carlo.png")

    # ---- chart 3: cumulative hours across the semester ----------------------------------------
    order_t = np.argsort([t["deadline"] for t in tasks], kind="stable")
    days = [tasks[j]["deadline"] for j in order_t]
    c0 = np.cumsum(sim[0]["hours"].mean(0)[order_t])
    c1 = np.cumsum(sim[1]["hours"].mean(0)[order_t])
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(days, c0, color=WITHOUT, linewidth=2, label="Without Winnie", drawstyle="steps-post")
    ax.plot(days, c1, color=WITH, linewidth=2, label="With Winnie", drawstyle="steps-post")
    ax.fill_between(days, c1, c0, step="post", color=WITH, alpha=0.08)
    ax.text(days[-1], c0[-1], f"  {c0[-1]:.0f} h", color=INK, va="center", fontsize=10.5)
    ax.text(days[-1], c1[-1], f"  {c1[-1]:.0f} h", color=INK, va="center", fontsize=10.5)
    ax.set_ylabel("Cumulative board hours", color=INK_2)
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %-d"))
    style(ax, "The gap grows all semester",
          "Cumulative expected board hours, tasks ordered by deadline (Aug–Dec 2026)")
    legend(ax, "upper left")
    save(fig, "03_cumulative_hours.png")

    # ---- chart 4: on-time rate by event (dumbbell) --------------------------------------------
    ev = defaultdict(list)
    for j, t in enumerate(tasks):
        ev[t["event"]].append(j)
    events = sorted((e for e in ev if len(ev[e]) >= 3),
                    key=lambda e: (sim[0]["late"][:, ev[e]] < 1).mean())
    fig, ax = plt.subplots(figsize=(11, 6.5))
    for i, e in enumerate(events):
        a = 100 * (sim[0]["late"][:, ev[e]] < 1).mean()
        b = 100 * (sim[1]["late"][:, ev[e]] < 1).mean()
        ax.plot([a, b], [i, i], color=GRID, linewidth=3, zorder=1)
        ax.scatter(a, i, s=80, color=WITHOUT, edgecolor=SURFACE, linewidth=2, zorder=2,
                   label="Without Winnie" if i == 0 else None)
        ax.scatter(b, i, s=80, color=WITH, edgecolor=SURFACE, linewidth=2, zorder=3,
                   label="With Winnie" if i == 0 else None)
        ax.text(b + 1.2, i, f"{b:.0f}%", va="center", fontsize=9.5, color=INK_2)
    ax.set_yticks(range(len(events)), [f"{e} ({len(ev[e])})" for e in events], color=INK)
    ax.set_xlim(50, 100)
    ax.set_ylim(-0.7, len(events) - 0.3)
    ax.set_xlabel("Tasks finished on time, within a day of the deadline (%)", color=INK_2)
    style(ax, "More tasks land on time, for every event",
          "Expected on-time rate by event (number of tasks); reminders, dependency alerts, reassignment",
          xgrid=True)
    legend(ax, "lower left")
    save(fig, "04_on_time_by_event.png")

    # ---- chart 5: peak weekly load per role (rebalancing) -------------------------------------
    mean_hours0 = sim[0]["hours"].mean(0)
    mean_hours1 = sim[1]["hours"].mean(0)
    load0 = weekly_role_load(tasks, mean_hours0)
    load1 = rebalance(weekly_role_load(tasks, mean_hours1))
    roles = sorted(load0, key=lambda r: max(load0[r].values()))
    fig, ax = plt.subplots(figsize=(11, 6.5))
    for i, r in enumerate(roles):
        a, b = max(load0[r].values()), max(load1[r].values())
        ax.plot([b, a], [i, i], color=GRID, linewidth=3, zorder=1)
        ax.scatter(a, i, s=80, color=WITHOUT, edgecolor=SURFACE, linewidth=2, zorder=2,
                   label="Without Winnie" if i == 0 else None)
        ax.scatter(b, i, s=80, color=WITH, edgecolor=SURFACE, linewidth=2, zorder=3,
                   label="With Winnie (+ reassignment)" if i == 0 else None)
    ax.set_yticks(range(len(roles)), roles, color=INK)
    ax.set_xlabel("Hours in that member's busiest week", color=INK_2)
    spread0 = np.std([max(v.values()) for v in load0.values()])
    spread1 = np.std([max(v.values()) for v in load1.values()])
    style(ax, "Busy weeks get lighter, and the load evens out",
          f"Busiest-week hours per role · spread across roles {spread0:.1f} h → {spread1:.1f} h "
          "with skill-matched reassignment", xgrid=True)
    legend(ax, "lower right")
    save(fig, "05_peak_week_by_role.png")

    # ---- chart 6: days from assigned to done by category -------------------------------------
    cyc = defaultdict(lambda: [[], []])
    for r in rows:
        cyc[r["category"]][0].append(r["days_to_done_without"])
        cyc[r["category"]][1].append(r["days_to_done_with_winnie"])
    order = sorted(cyc, key=lambda c: np.mean(cyc[c][0]))
    y = np.arange(len(order))
    fig, ax = plt.subplots(figsize=(11, 6.5))
    ax.barh(y + h / 2 + 0.01, [np.mean(cyc[c][0]) for c in order], h, color=WITHOUT, label="Without Winnie")
    ax.barh(y - h / 2 - 0.01, [np.mean(cyc[c][1]) for c in order], h, color=WITH, label="With Winnie")
    for i, c in enumerate(order):
        a, b = np.mean(cyc[c][0]), np.mean(cyc[c][1])
        ax.text(a + 0.15, i + h / 2, f"{a - b:.1f} days sooner", va="center", fontsize=9.5, color=INK_2)
    ax.set_yticks(y, order, color=INK)
    ax.set_xlabel("Average calendar days from assigned to done", color=INK_2)
    style(ax, "Handoffs stop stalling",
          "Tasks that wait on another role (orders, listings, slides, planning) speed up the most",
          xgrid=True)
    legend(ax, "lower right")
    save(fig, "06_days_to_done_by_category.png")
    print(f"\nWrote data/winnie_simulation.csv ({len(rows)} tasks), data/summary.csv, charts/*.png")


if __name__ == "__main__":
    main()
