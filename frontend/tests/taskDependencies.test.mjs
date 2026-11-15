import assert from "node:assert/strict";
import { test } from "node:test";
import { inferTaskDependencies } from "../src/lib/taskDependencies.js";

test("infers the candidate shortlist, deliberation, and announcement chain", () => {
  const people = [
    { id: "president", role: "President" },
    { id: "vice-president", role: "Vice President" },
  ];
  const tasks = [
    { id: "shortlist", title: "Shortlist interview candidates", event: "E-Board Recruitment", assignee: "vice-president" },
    { id: "deliberation", title: "External E-Board deliberation", event: "E-Board Recruitment", assignee: "president" },
    { id: "announcement", title: "Announce E-Board candidate decisions", event: "E-Board Recruitment", assignee: "president" },
  ];

  assert.deepEqual(inferTaskDependencies(tasks, people).map(({ task_id, depends_on_id }) => [
    task_id, depends_on_id,
  ]), [
    ["deliberation", "shortlist"],
    ["announcement", "deliberation"],
  ]);
});

test("uses event-coordinator and treasurer roles and avoids cross-event links", () => {
  const people = [
    { id: "events", role: "Event Coordinator Co-Chair" },
    { id: "treasurer", role: "Treasurer" },
  ];
  const tasks = [
    { id: "list", title: "Create supply purchase list", event: "GirlHacks", assignee: "events" },
    { id: "purchase", title: "Purchase event materials", event: "GirlHacks", assignee: "treasurer" },
    { id: "other-purchase", title: "Purchase event materials", event: "WiCS Gala", assignee: "treasurer" },
  ];

  assert.deepEqual(inferTaskDependencies(tasks, people).map(({ task_id, depends_on_id }) => [
    task_id, depends_on_id,
  ]), [["purchase", "list"]]);
});

test("does not suggest links already stored or links that would create a cycle", () => {
  const tasks = [
    { id: "shortlist", title: "Shortlist interview candidates" },
    { id: "deliberation", title: "External E-Board deliberation", dependsOn: ["shortlist"] },
    { id: "announcement", title: "Announce E-Board candidate decisions", dependsOn: ["deliberation"] },
  ];

  assert.deepEqual(inferTaskDependencies(tasks), []);
});

test("respects an explicit prerequisite named in a task description", () => {
  const tasks = [
    { id: "booking", title: "Confirm room booking" },
    { id: "flyer", title: "Prepare event flyer", description: "Publish after Confirm room booking." },
  ];

  assert.deepEqual(inferTaskDependencies(tasks).map(({ task_id, depends_on_id }) => [
    task_id, depends_on_id,
  ]), [["flyer", "booking"]]);
});
