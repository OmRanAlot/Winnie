import { useState, useEffect, useCallback, useRef, Fragment } from "react";
import { getAssignments, getCandidates, getMembers, getTasks, updateTaskStatus, weekStart } from "./lib/api.js";
import Recorder from "./Recorder.jsx";
import { supabase } from "./lib/supabase";
import { reassignmentStore } from "./lib/reassignments.js";
const requestsStore = reassignmentStore(supabase);

// Meeting previews remain separate from the live task and request data.
/* ---------- Placeholder data (replace with backend responses) ---------- */
// Sample people: shown when the backend is unreachable, and still used by the sample
// Meetings / Requests screens. Real members come from GET /api/members.
const SAMPLE_PEOPLE = [
  { id: 1, name: "Lakshita Madhavan", role: "President", skills: ["Leadership", "Public speaking", "Budgeting"] },
  { id: 2, name: "Stephanie Nicolaescu", role: "Vice President", skills: ["Planning", "Outreach", "Docs"] },
  { id: 4, name: "Anne Therese Argonza", role: "Secretary", skills: ["Note-taking", "Scheduling", "Docs"] },
  { id: 3, name: "Sharanya Raj", role: "Treasurer", skills: ["Budgeting", "Spreadsheets", "Sponsorship"] },
  { id: 5, name: "Saidarsha Karunakaran", role: "Event Coordinator", skills: ["Logistics", "Planning", "Vendors"] },
  { id: 6, name: "Garima Thapa", role: "Event Coordinator", skills: ["Design", "Logistics", "Outreach"] },
  { id: 9, name: "Carlin Verano", role: "Industry Partnerships Chair", skills: ["Outreach", "Sponsorship", "Networking"], previousRoles: [] },
  { id: 10, name: "Manisha Palaniappan", role: "Industry Partnerships Chair", skills: ["Sponsorship", "Writing", "Networking"], previousRoles: [] },
  { id: 7, name: "Caithy Liao", role: "Public Relations Chair", skills: ["Design", "Social media", "Writing"] },
  { id: 8, name: "Azka Faisal", role: "Public Relations Chair", skills: ["Photography", "Writing", "Outreach"] },
  { id: 11, name: "Priya Patel", role: "Community Outreach Chair", skills: ["Outreach", "Community Engagement", "Event Planning"], previousRoles: [] },
  { id: 12, name: "Meera James", role: "Technical Director", skills: ["Web Development", "Technical", "Design"], previousRoles: [] },
  { id: 13, name: "Diya Pottangadi", role: "Membership Chair", skills: ["Membership", "Community Engagement", "Outreach", "Event Planning"], previousRoles: [] },
];
// Sample tasks, shown only when the backend can't be reached. Real tasks come from GET /api/tasks.
// day = start column (0 = Mon), len = days wide, dep = id of task it depends on
const SAMPLE_TASKS = [
  { id: 1, title: "Draft GBM 1 agenda", assigned: "11/02/2026", start: "11/09/2026", due: "11/10/2026", finished: "11/10/2026", assignee: 2, status: "Completed", dep: null, day: 0, len: 1.2, notes: "" },
  { id: 2, title: "Book GBM 1 room", assigned: "11/02/2026", start: "11/10/2026", due: "11/11/2026", finished: "", assignee: 5, status: "In-Progress", priority: "high", dep: 1, day: 1, len: 1.2, notes: "Waiting on facilities reply." },
  { id: 3, title: "Allocate budget for GBM 1", assigned: "11/03/2026", start: "11/11/2026", due: "11/13/2026", finished: "", assignee: 3, status: "Upcoming", priority: "high", dep: 2, day: 2, len: 2, notes: "" },
  { id: 4, title: "Design GBM 1 flyer", assigned: "11/03/2026", start: "11/10/2026", due: "11/12/2026", finished: "", assignee: 7, status: "In-Progress", dep: null, day: 1, len: 2, notes: "" },
  { id: 5, title: "Post flyer on socials", assigned: "11/04/2026", start: "11/12/2026", due: "11/14/2026", finished: "", assignee: 8, status: "Upcoming", dep: 4, day: 3, len: 1.6, notes: "" },
  { id: 6, title: "Order snacks", assigned: "11/04/2026", start: "11/13/2026", due: "11/15/2026", finished: "", assignee: 5, initialAssignee: 6, status: "Upcoming", priority: "low", dep: 3, day: 4, len: 1.8, notes: "" },
  { id: 7, title: "Draft RSVP form", assigned: "11/04/2026", start: "11/10/2026", due: "11/11/2026", finished: "", assignee: 4, status: "Upcoming", dep: 1, day: 1, len: 1, notes: "" },
  { id: 8, title: "Share RSVP form", assigned: "11/05/2026", start: "11/11/2026", due: "11/12/2026", finished: "", assignee: 8, status: "Upcoming", dep: 7, day: 2, len: 1.2, notes: "" },
  { id: 9, title: "Prepare event layout", assigned: "11/05/2026", start: "11/12/2026", due: "11/14/2026", finished: "", assignee: 5, status: "Upcoming", dep: 2, day: 3, len: 1.5, notes: "" },
  { id: 10, title: "Print GBM 1 flyers", assigned: "11/06/2026", start: "11/12/2026", due: "11/13/2026", finished: "", assignee: 7, status: "Upcoming", dep: 4, day: 3, len: 1.2, notes: "" },
  { id: 11, title: "Confirm catering delivery", assigned: "11/06/2026", start: "11/14/2026", due: "11/15/2026", finished: "", assignee: 6, status: "Upcoming", dep: 6, day: 5, len: 1.5, notes: "" },
  { id: 12, title: "Confirm GBM 1 event plan", assigned: "11/06/2026", start: "11/11/2026", due: "11/12/2026", finished: "", assignee: 1, status: "Upcoming", priority: "high", dep: 1, day: 2, len: 1, notes: "" },
  { id: 13, title: "Review final event budget", assigned: "11/07/2026", start: "11/13/2026", due: "11/14/2026", finished: "", assignee: 1, status: "Upcoming", priority: "high", dep: 3, day: 4, len: 1, notes: "" },
  { id: 14, title: "Prepare opening remarks", assigned: "11/07/2026", start: "11/11/2026", due: "11/12/2026", finished: "", assignee: 2, status: "Upcoming", dep: 1, day: 2, len: 1, notes: "" },
  { id: 15, title: "Send GBM 1 reminder", assigned: "11/08/2026", start: "11/13/2026", due: "11/14/2026", finished: "", assignee: 2, status: "Upcoming", dep: 8, day: 4, len: 1, notes: "" },
  { id: 16, title: "Review room layout", assigned: "11/08/2026", start: "11/14/2026", due: "11/15/2026", finished: "", assignee: 2, status: "Upcoming", dep: 9, day: 5, len: 1, notes: "" },
  { id: 17, title: "Collect final RSVP count", assigned: "11/09/2026", start: "11/14/2026", due: "11/15/2026", finished: "", assignee: 2, status: "Upcoming", dep: 8, day: 5, len: 1, notes: "" },
  // Keep the offline metrics chart representative across every member and task status.
  ...SAMPLE_PEOPLE.flatMap((member, index) => {
    const id = 18 + index * 4;
    const otherMember = SAMPLE_PEOPLE[(index + 1) % SAMPLE_PEOPLE.length];
    const base = {
      assigned: "11/09/2026", start: "11/09/2026", assignee: member.id,
      dep: null, day: index % 7, len: 1.2, notes: "",
    };
    const firstName = member.name.split(" ")[0];
    return [
      { ...base, id, title: `Complete ${firstName}'s weekly update`, due: "11/12/2026", finished: "11/12/2026", status: "Completed" },
      { ...base, id: id + 1, title: `Prepare ${firstName}'s next-step plan`, due: "12/15/2026", finished: "", status: "Upcoming" },
      { ...base, id: id + 2, title: `Submit ${firstName}'s status update`, due: "11/12/2026", finished: "", status: "Upcoming" },
      { ...base, id: id + 3, title: `Coordinate ${firstName}'s follow-up`, initialAssignee: otherMember.id, due: "12/18/2026", finished: "", status: "Upcoming" },
    ];
  }),
].map((t) => ({ ...t, initialAssignee: t.initialAssignee ?? t.assignee, priority: t.priority ?? "normal" }));
const MEETINGS = [
  { id: 1, date: "11/13/26", name: "Fall 2026 E-Board Meeting", attendees: [1, 2, 3, 5, 7], tasks: [[ "Allocate budget for GBM 1", 3], ["Design GBM 1 flyer", 7]] },
  { id: 2, date: "11/10/26", name: "Finance Logistics Meeting", attendees: [1, 3, 5], tasks: [["Book GBM 1 room", 5]] },
  { id: 3, date: "11/06/26", name: "P/VP Transition Meeting", attendees: [1, 2, 4], tasks: [["Draft GBM 1 agenda", 2]] },
];
const REQUESTS = [
  { id: 1, task: 3, from: 3, to: 1, reason: "I have a schedule conflict and need someone else to handle the budget.", status: "pending", requestedAt: "11/13/2026" },
  { id: 2, task: 5, from: 8, to: 7, reason: "I need support finishing the social media posts before the deadline.", status: "pending", requestedAt: "11/12/2026" },
  { id: 3, task: 6, from: 6, to: 5, reason: "The event order is already being coordinated by another coordinator.", status: "approved", requestedAt: "11/10/2026" },
];

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const COLORS = { Upcoming: "#e0b25a", "In-Progress": "#cc6a3d", Completed: "#7a2c22" };
const REASSIGNED_COLOR = "#f3ebe2";
const EMPTY_PLAN_INPUT = { name: "", description: "", startDate: "", dueDate: "", time: "" };
const EMPTY_TASK_FORM = { title: "", description: "", startDate: "", dueDate: "", time: "", priority: "normal", summary: "" };
const uiDate = (iso) => iso ? `${iso.slice(5, 7)}/${iso.slice(8, 10)}/${iso.slice(0, 4)}` : "";
// Kept in sync with App's state so the helpers below see live data; sample ids still resolve
// for the screens that are not connected yet.
let currentPeople = SAMPLE_PEOPLE;
let currentTasks = SAMPLE_TASKS;
const person = (id) => currentPeople.find((p) => p.id === id) ?? SAMPLE_PEOPLE.find((p) => p.id === id);
const task = (id) => currentTasks.find((t) => t.id === id) ?? SAMPLE_TASKS.find((t) => t.id === id);
const owns = (t, id) => t.assignee === id || (t.assignees ?? []).includes(id);
const seedOf = (id) => [...String(id)].reduce((a, c) => a + c.charCodeAt(0), 0);
const dueDateKey = (t) => {
  if (t.dueIso) {
    const time = Date.parse(t.dueIso);
    if (!Number.isNaN(time)) return time;
  }
  const match = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(t.due ?? "");
  return match ? Date.UTC(Number(match[3]), Number(match[1]) - 1, Number(match[2])) : Infinity;
};
const compareByDueDate = (a, b) => {
  const aDue = dueDateKey(a), bDue = dueDateKey(b);
  return aDue < bDue ? -1 : aDue > bDue ? 1 : 0;
};
// Live tasks have no member link yet: fall back to the tracker's assignee cell.
const who = (t) => person(t.assignee) ?? { id: null, name: t.assigneeText ? t.assigneeText.split("\n")[0] : "Unassigned" };

/* ---------- Styles (palette pulled from the logo) ---------- */
export const CSS = `
:root{--ink:#3a1410;--maroon:#5a0d05;--rust:#b5472a;--paper:#f3ebe2;--surface:#eadfd2;--hover:#e0d0bf;--line:#d6c4b2;--muted:#7a6459;--sun:#e0b25a;--s1:4px;--s2:8px;--s3:12px;--s4:16px;--s5:24px;--s6:32px;--r:6px;--frame-band:clamp(12px,6.6vw,96px)}
html{scrollbar-gutter:stable both-edges}
*{box-sizing:border-box}
body{margin:0;background:var(--maroon);color:var(--ink);font-family:"Kabel","Josefin Sans","Hanken Grotesk","Segoe UI",system-ui,sans-serif;font-size:16px;line-height:1.5}
a{color:var(--maroon)}
a:hover{color:var(--rust)}
h1,h2,h3,h4,.big{font-family:"Righteous","Hanken Grotesk",system-ui,sans-serif;letter-spacing:.07em}
button.btn,button.pill,button.link,button.bell,button.back,button.chev,button.rb,.nav button,.hub button{font-family:"Righteous","Hanken Grotesk",system-ui,sans-serif;letter-spacing:.07em}
.app{max-width:calc(1120px + var(--frame-band) + var(--frame-band));width:calc(100% - var(--frame-band) - var(--frame-band));margin:0 auto;min-height:100vh;display:flex;flex-direction:column;padding:var(--s5) var(--s6) 0;background:var(--paper);border-left:var(--frame-band) solid var(--rust);border-right:var(--frame-band) solid var(--rust)}
.page-content{display:flex;flex:1;flex-direction:column;min-width:0;padding-bottom:48px}
.top{display:flex;align-items:center;gap:var(--s4);min-height:56px;margin-bottom:var(--s4)}
.top h1{flex:1;text-align:center;font-size:28px;margin:0;font-weight:700;letter-spacing:.07em}
.top .greeting{text-align:left;font-size:40px;font-weight:600}
.top .sp{width:44px}
.back{border:1.5px solid var(--ink);background:transparent;color:var(--ink);width:44px;height:44px;border-radius:50%;cursor:pointer;display:grid;place-items:center}
.back:hover{background:var(--ink);color:var(--paper)}
.adm{color:var(--rust);font-weight:700;font-size:15px;min-width:96px;text-align:right;letter-spacing:.02em}
button{font-family:inherit}
.btn{border:0;background:var(--rust);color:#fff8f0;font-weight:650;font-size:15px;padding:var(--s3) var(--s5);border-radius:var(--r);cursor:pointer}
.btn:hover{background:var(--maroon)}
.btn.alt{background:var(--surface);color:var(--ink);border:1px solid var(--line)}.btn.alt:hover{background:var(--hover)}
.btn.out{background:transparent;color:var(--ink);border:1.5px solid var(--ink)}.btn.out:hover{background:var(--ink);color:var(--paper)}
.link{background:none;border:0;color:var(--ink);text-decoration:underline;text-underline-offset:4px;font-size:16px;cursor:pointer;margin-top:var(--s2)}
button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:3px solid var(--sun);outline-offset:2px}
.center{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:var(--s4);padding-bottom:var(--s6)}
.center h2{font-size:40px;margin:0;font-weight:700;letter-spacing:.07em;border-bottom:2px solid var(--ink);padding:0 var(--s6) var(--s3);width:min(640px,100%);text-align:center}
.logo{width:132px;height:132px;object-fit:contain}
.form{display:grid;grid-template-columns:auto 280px;gap:var(--s3) var(--s4);align-items:center;text-align:right;font-weight:600}
.field{border:1px solid var(--line);background:#f9f4ee;border-radius:var(--r);padding:var(--s3) var(--s4);font-size:16px;color:var(--ink);font-family:inherit;width:100%}
textarea.field{min-height:110px;resize:vertical}
.pill{background:var(--surface);border-radius:var(--r);padding:var(--s3) var(--s4);font-size:16px;font-weight:500;border:0;color:var(--ink);text-align:left;font-family:inherit}
button.pill{cursor:pointer}button.pill:hover{background:var(--hover)}
.panel{background:var(--surface);border-radius:var(--r);padding:var(--s5)}
.panel h3{margin:0 0 var(--s3);font-size:20px;font-weight:650}
.panel ul{margin:0;padding-left:var(--s5);line-height:1.9}
.panel .none,.empty{color:var(--muted);list-style:none;margin-left:calc(var(--s5) * -1)}
.empty{grid-column:1/-1;margin:0;padding:var(--s2) 0}
.two{display:grid;grid-template-columns:1fr 1fr;gap:var(--s5)}
.avatar{width:52px;height:52px;border-radius:50%;background:#f0c9b3;border:2px solid var(--maroon);box-shadow:2px 2px 0 var(--maroon);display:grid;place-items:center;font-weight:700;color:var(--maroon);flex:none;cursor:pointer;padding:0;font-size:16px}
.avatar:hover{background:var(--sun)}
.avatar.sm{width:40px;height:40px;font-size:13px}
.avatar.lg{width:104px;height:104px;font-size:34px;cursor:default;box-shadow:4px 4px 0 var(--maroon)}
.id{display:flex;gap:var(--s5);align-items:center;margin-bottom:var(--s4)}
.id h2{margin:0;font-size:32px;font-weight:700;border-bottom:2px solid var(--ink);padding-bottom:var(--s2);flex:1;max-width:640px}
.id p{margin:var(--s2) 0 0;font-size:18px;color:var(--muted)}
.grid2{display:grid;grid-template-columns:1fr 2px 1fr;gap:var(--s5) var(--s6);margin-top:var(--s5)}
.divider{border-left:2px dashed var(--ink);grid-row:1/5;grid-column:2}
.row{display:flex;align-items:center;gap:var(--s3)}.row .pill{flex:1;text-align:left}
.home{display:grid;grid-template-columns:1fr 320px;gap:var(--s6);flex:1;min-width:0}
.home>div,.gantt{min-width:0;width:100%}
.home h3{font-size:22px;margin:0 0 var(--s3);font-weight:650}
.gantt-controls{display:flex;align-items:center;justify-content:flex-end;gap:var(--s3);flex-wrap:wrap}
.gantt-controls.admin-controls{justify-content:space-between}
.nav{display:grid;grid-template-columns:1fr 1fr 1fr;gap:var(--s5);background:var(--surface);border-top:1px solid var(--line);margin:0 calc(var(--s6) * -1);padding:var(--s4) var(--s6);position:sticky;bottom:0;z-index:5}
.nav button{border:1px solid var(--line);background:var(--paper);border-radius:var(--r);padding:var(--s3);font-size:20px;font-weight:600;color:var(--ink);cursor:pointer}
.nav button:hover{background:var(--ink);color:var(--paper)}
.bell{position:relative;background:none;border:0;color:var(--ink);cursor:pointer;padding:var(--s2);display:grid}
.bell b{position:absolute;right:0;top:0;background:var(--rust);color:#fff;border-radius:50%;width:18px;height:18px;font-size:11px;display:grid;place-items:center}
.due{display:flex;align-items:center;gap:var(--s3);margin-bottom:var(--s2)}
.due .pill{flex:1;min-width:0}
.status-action{padding:var(--s2) var(--s3);font-size:13px;white-space:nowrap}
.due-task{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.status-switch{display:inline-flex;align-items:center;gap:var(--s2);padding:var(--s2) var(--s3);border:1px solid var(--line);border-radius:999px;background:var(--surface);color:var(--ink);font-size:12px;white-space:nowrap;cursor:pointer}
.status-switch-track{position:relative;display:inline-block;width:34px;height:20px;flex:none;border-radius:999px;background:var(--line)}
.status-switch-track i{position:absolute;top:3px;left:3px;width:14px;height:14px;border-radius:50%;background:var(--ink);transition:left .15s}
.status-switch.on .status-switch-track{background:var(--rust)}
.status-switch.on .status-switch-track i{left:17px;background:#fff8f0}
.gantt{background:var(--surface);border-radius:var(--r);overflow:hidden;font-size:13px}
.gh,.gr{display:grid;grid-template-columns:150px 70px 84px 84px 84px 1fr;align-items:center}
.gh{background:var(--hover);font-weight:700;padding:var(--s2) var(--s3);gap:var(--s1)}
.gr{padding:var(--s1) var(--s3);gap:var(--s1);height:40px;border-top:1px solid var(--line);cursor:pointer}
.gr span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.priority-high{color:var(--maroon);font-weight:700}
.priority-low{color:var(--muted)}
.days{display:grid;grid-template-columns:repeat(7,1fr);text-align:center;font-weight:700}
.lane{position:relative;height:100%;background:repeating-linear-gradient(90deg,transparent 0 calc(100%/7 - 1px),var(--line) calc(100%/7 - 1px) calc(100%/7))}
.bar{position:absolute;top:10px;height:20px;border-radius:3px}
.bar.related-bar{outline:2px solid var(--rust);outline-offset:1px}
.bar.linked-highlight{outline:3px solid var(--maroon);outline-offset:1px;filter:saturate(1.25) brightness(1.08)}
.bar.unrelated-dim{opacity:.4}
.tog{display:flex;align-items:center;gap:var(--s2);justify-content:flex-end;font-size:14px;margin-bottom:var(--s2);padding:0;border:0;background:transparent;color:inherit;cursor:pointer}
.sw{width:40px;height:22px;border-radius:99px;background:var(--line);position:relative}
.sw i{position:absolute;top:3px;left:3px;width:16px;height:16px;border-radius:50%;background:var(--ink);transition:left .15s}
.sw.on{background:var(--rust)}.sw.on i{left:21px;background:#fff8f0}
.legend{display:flex;gap:var(--s4);margin-top:var(--s3);font-size:14px}
.legend i{display:inline-block;width:14px;height:14px;border-radius:3px;margin-right:var(--s2);vertical-align:-2px}
.legend .related-swatch{background:transparent;border:2px solid var(--rust)}
.sec{font-size:22px;margin:var(--s5) 0 var(--s2);font-weight:650}
.sum{display:grid;grid-template-columns:1fr 240px;gap:var(--s2) var(--s4);align-items:center;max-width:960px;margin:0 auto;width:100%}
.sum .pill{display:flex;justify-content:space-between;align-items:center;width:100%;cursor:pointer}
.chev{background:none;border:0;cursor:pointer;color:var(--ink);display:grid;transition:transform .15s}
.chev.open{transform:rotate(180deg)}
.det{grid-column:1/-1;background:#f9f4ee;border:1px solid var(--line);border-radius:var(--r);padding:var(--s3) var(--s4);margin:0 0 var(--s2);font-size:15px}
.modal{position:fixed;inset:0;background:rgba(58,20,16,.4);display:grid;place-items:center;z-index:9}
.box{background:var(--paper);border:2px solid var(--ink);border-radius:var(--r);padding:var(--s5) var(--s6);max-width:480px;font-size:18px;line-height:1.6}
.box h4{margin:0 0 var(--s2);font-size:22px}
.box .acts{display:flex;gap:var(--s3);margin-top:var(--s4)}
.toast{position:fixed;bottom:96px;left:50%;transform:translateX(-50%);background:var(--ink);color:var(--paper);padding:var(--s3) var(--s5);border-radius:var(--r);z-index:10;font-weight:600}
.hub{display:grid;grid-template-columns:1fr 1fr;gap:var(--s4);max-width:880px;margin:var(--s6) auto}
.hub button{background:var(--surface);border:1px solid var(--line);padding:var(--s6);font-size:22px;font-weight:650;color:var(--ink);border-radius:var(--r);cursor:pointer;text-align:left}
.hub button:hover{background:var(--ink);color:var(--paper)}.hub button:last-child:nth-child(odd){grid-column:1/-1;justify-self:center;width:50%}
.admin-sections{max-width:960px;width:100%;margin:0 auto}
.admin-section{margin:var(--s5) 0}
.admin-section h2{font-size:22px;margin:0;text-align:center}
.admin-section>p,.grid-intro{margin:var(--s2) auto 0;text-align:center;color:var(--muted);max-width:680px}
.admin-hub{grid-template-columns:repeat(3,minmax(0,1fr));margin:var(--s4) auto}
.admin-hub button{display:flex;flex-direction:column;gap:var(--s2);min-height:120px;padding:var(--s4)}
.admin-hub button:last-child:nth-child(odd){grid-column:auto;justify-self:stretch;width:auto}
.admin-card-title{font-size:19px}
.admin-card-description{font:500 14px/1.45 "Hanken Grotesk","Segoe UI",system-ui,sans-serif;letter-spacing:0}
.admin-menu{display:grid;grid-template-columns:minmax(0,1fr);gap:var(--s4);max-width:520px;margin:var(--s6) auto}
.admin-menu button{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:var(--s4) var(--s5);color:var(--ink);font:600 22px "Righteous","Hanken Grotesk",system-ui,sans-serif;letter-spacing:.04em;cursor:pointer}
.admin-menu button:hover{background:var(--ink);color:var(--paper)}
.metrics-overview{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(190px,.8fr) minmax(210px,.9fr);gap:var(--s4);align-items:stretch}
.metrics-overview .panel{min-width:0;margin:0}
.metrics-overview h2{font-size:20px;margin:0 0 var(--s3);text-align:center}
.metrics-legend{display:flex;justify-content:center;flex-wrap:wrap;gap:var(--s2);font-size:11px;margin-bottom:var(--s3)}
.metrics-legend span{display:inline-flex;align-items:center;gap:4px}
.metrics-legend i{width:9px;height:9px;border-radius:50%;display:inline-block}
.metrics-overview .metrics-chart-panel{background:#fff;border:1px solid var(--line);border-radius:22px;padding:24px 18px}
.metrics-chart-panel h2{font-family:"Righteous","Hanken Grotesk",system-ui,sans-serif;font-size:22px;line-height:1.2;letter-spacing:.07em;color:#251612}
.metrics-chart-scroll{overflow-x:auto}
.task-metrics-chart{display:block;width:100%;min-width:330px;height:auto;overflow:visible}
.task-metrics-chart .chart-member{cursor:pointer}
.task-metrics-chart .chart-member:focus{outline:none}
.task-metrics-chart .chart-member:focus rect{stroke:var(--maroon);stroke-width:2}
.task-metrics-chart text{font-family:"Kabel","Josefin Sans","Hanken Grotesk","Segoe UI",system-ui,sans-serif;fill:#33221d}
.metrics-recent-list,.metrics-member-list{display:flex;flex-direction:column;gap:var(--s2);max-height:360px;overflow:auto}
.metrics-request,.metrics-member-link{background:var(--paper);border:1px solid var(--line);border-radius:var(--r);padding:var(--s2) var(--s3);color:var(--ink);text-align:left}
.metrics-request{font-size:13px;line-height:1.35}
.metrics-member-link{display:flex;align-items:center;gap:var(--s2);cursor:pointer}
.metrics-member-link:hover{background:var(--hover)}
.metrics-member-link .avatar{flex:none}
.metrics-member-link span{min-width:0}
.metrics-member-link small{display:block;color:var(--muted)}
.metrics-stat-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:var(--s3);margin:var(--s4) 0}
.metrics-stat{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:var(--s3);text-align:center}
.metrics-stat strong{display:block;font:700 28px "Righteous","Hanken Grotesk",system-ui,sans-serif;color:var(--rust)}
.metrics-stat span{font-size:13px}
.metrics-task-list{display:grid;grid-template-columns:1fr 1fr;gap:var(--s4)}
.metrics-task-list .panel h3{margin-top:0}
.reassignment-chart{display:grid;gap:var(--s3)}
.reassignment-bar-row{display:grid;grid-template-columns:130px 1fr 30px;gap:var(--s2);align-items:center;font-size:14px}
.reassignment-bar-track{height:12px;border-radius:999px;background:var(--surface);overflow:hidden}
.reassignment-bar-track i{height:100%;display:block;background:var(--rust)}
.attendance-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--s2)}
.attendance-member{display:flex;align-items:center;gap:var(--s2);background:var(--surface);border-radius:var(--r);padding:var(--s2)}
.attendance-member input{width:18px;height:18px;accent-color:var(--rust)}
.metrics-note{color:var(--muted);font-size:13px}
.lbl{font-weight:700}
.meter{height:10px;background:#f9f4ee;border-radius:2px;overflow:hidden}.meter i{display:block;height:100%;background:var(--rust)}
.score{display:grid;grid-template-columns:1fr 1fr;gap:var(--s5)}
.big{font-size:56px;font-weight:700;color:var(--rust);line-height:1.1}
.cols{display:grid;grid-template-columns:1fr 1fr 1fr;gap:var(--s5)}
.cols .panel{min-height:320px}
.cols .panel p{white-space:pre-wrap;font-size:15px;line-height:1.7;margin:0}
.req{display:flex;align-items:center;gap:var(--s4);margin-bottom:var(--s4)}
.req .panel{flex:1;font-size:18px;line-height:1.6}
.rb{width:48px;height:48px;border-radius:50%;border:0;color:#fff8f0;cursor:pointer;display:grid;place-items:center}
.side{display:flex;flex-direction:column;gap:var(--s3)}.side .pill{background:var(--ink);color:var(--paper);cursor:pointer}
.task-form{grid-template-columns:150px minmax(0,1fr)}
.plan-task-form{display:grid;grid-template-columns:1fr 1fr;gap:var(--s4);max-width:920px;margin:0 auto;width:100%}
.plan-task-form .wide{grid-column:1/-1}
.plan-task-form label,.create-task-grid label{display:flex;flex-direction:column;gap:var(--s2);font-weight:600}
.plan-task-dates{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:var(--s4)}
.plan-task-actions,.create-task-actions{display:flex;justify-content:center;align-items:center;gap:var(--s3);flex-wrap:wrap;margin:var(--s5) auto 0}
.create-task-grid{display:grid;grid-template-columns:minmax(0,.9fr) minmax(0,1.1fr);gap:var(--s5)}
.create-task-grid .panel{min-width:0}
.create-task-fields{display:grid;grid-template-columns:1fr;gap:var(--s3)}
.task-summary{min-height:260px;resize:vertical}
.plan-error{max-width:920px;margin:var(--s4) auto 0;padding:var(--s3) var(--s4);background:#f4e3d7;border:1px solid var(--rust);border-radius:var(--r);color:var(--maroon);font-weight:600}
.dependency-lines{position:absolute;top:0;right:10px;width:calc(100% - 510px);pointer-events:none}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
@media(max-width:800px){
  .app{padding:var(--s4)}
  .nav{margin:0 calc(var(--s4) * -1);padding:var(--s3) var(--s4);gap:var(--s2)}
  .home,.two,.cols,.score,.hub{grid-template-columns:1fr}
  .metrics-overview{grid-template-columns:1fr}
  .metrics-stat-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .metrics-task-list{grid-template-columns:1fr}
  .admin-menu{max-width:100%}
  .create-task-grid{grid-template-columns:1fr}
  .home,.home>div,.gantt,.gh,.gr{min-width:0;width:100%}
  .meeting-layout{grid-template-columns:1fr!important}
  .task-form{grid-template-columns:minmax(0,100px) minmax(0,1fr)!important}
  .gh,.gr{grid-template-columns:minmax(0,110px) 56px 0 0 0 minmax(0,1fr)}
  .gh span:nth-child(3),.gh span:nth-child(4),.gh span:nth-child(5),.gr span:nth-child(3),.gr span:nth-child(4),.gr span:nth-child(5){display:none}
  .grid2{grid-template-columns:1fr}
  .grid2 .row{grid-column:1!important;grid-row:auto!important}
  .divider{display:none}
  .sum{grid-template-columns:1fr}
  .hub button:last-child:nth-child(odd){width:100%}
  .dependency-lines{width:calc(100% - 208px)}
}
@media(max-width:520px){
  .app{padding:var(--s3);border-radius:0}
  .top{gap:var(--s2);min-height:44px}
  .top .sp{width:20px}
  .top h1{font-size:clamp(16px,5vw,21px);letter-spacing:1px}
  .top .greeting{font-size:clamp(21px,7vw,30px);letter-spacing:.07em}
  .adm{min-width:0;font-size:11px}
  .back{width:38px;height:38px}
  .center h2{font-size:clamp(24px,8vw,34px);padding-right:var(--s3);padding-left:var(--s3)}
  .logo{width:104px;height:104px}
  .form{grid-template-columns:minmax(0,1fr);gap:var(--s2);width:min(100%,360px);text-align:left}
  .id{gap:var(--s3)}
  .avatar.lg{width:80px;height:80px;font-size:26px}
  .id h2{font-size:clamp(21px,7vw,28px);overflow-wrap:anywhere}
  .home h3{font-size:19px}
  .plan-task-form,.plan-task-dates{grid-template-columns:1fr}
  .plan-task-form .wide{grid-column:auto}
  .gantt-controls,.gantt-controls.admin-controls{align-items:flex-start;flex-direction:column}
  .nav{gap:var(--s1);padding:var(--s2)}
  .nav button{min-width:0;padding:var(--s2) 4px;font-size:clamp(12px,3.7vw,16px)}
  .due{gap:var(--s2)}
  .due .pill{padding:var(--s2);font-size:14px}
  .st{font-size:11px}
  .status-action{padding:var(--s2);font-size:11px}
  .panel{padding:var(--s4)}
  .gh,.gr{grid-template-columns:minmax(0,92px) 44px 0 0 0 minmax(0,1fr)}
  .dependency-lines{width:calc(100% - 178px)}
  .gantt{font-size:11px}
  .legend{flex-wrap:wrap;gap:var(--s2)}
  .hub button{padding:var(--s4)}
  .attendance-list{grid-template-columns:1fr}
  .reassignment-bar-row{grid-template-columns:105px 1fr 24px;font-size:12px}
  .req{flex-wrap:wrap}
  .req .panel{flex-basis:100%}
  .rb{flex:1}
  .box{width:min(480px,calc(100vw - 32px));max-height:calc(100vh - 32px);overflow:auto;padding:var(--s4)}
  .toast{max-width:calc(100% - 32px);text-align:center}
}
`;

const DESIGN_REFRESH_ENABLED = true; // Set false to restore the current styling.
const DESIGN_REFRESH_CSS = `
.app.design-refresh{background-image:radial-gradient(ellipse at 50% 0,rgba(255,255,255,.48),transparent 58%)}
.app.design-refresh .top{position:relative;padding-bottom:8px}
.app.design-refresh .top::after{content:"";position:absolute;left:8%;right:8%;bottom:0;height:1px;background:linear-gradient(90deg,transparent,var(--line),transparent)}
.app.design-refresh .top h1::after{content:"";display:block;width:38px;height:3px;margin:5px auto 0;border-radius:99px;background:var(--rust)}
.app.design-refresh .top .greeting::after{margin-left:0}
.app.design-refresh .panel{border:1px solid rgba(214,196,178,.88);border-radius:14px;box-shadow:0 6px 18px rgba(58,20,16,.07),inset 0 1px rgba(255,255,255,.55);background-image:linear-gradient(145deg,rgba(255,255,255,.25),transparent 58%)}
.app.design-refresh .panel>h3:first-child{padding-bottom:var(--s2);border-bottom:1px solid rgba(214,196,178,.8)}
.app.design-refresh .metrics-chart-panel{background-color:#fff;border-radius:22px;box-shadow:0 8px 24px rgba(58,20,16,.08)}
.app.design-refresh .nav{border:1px solid var(--line);border-bottom:0;border-radius:16px 16px 0 0;background:linear-gradient(180deg,#f1e7dc,var(--surface));box-shadow:0 -8px 22px rgba(58,20,16,.07)}
.app.design-refresh .nav button,.app.design-refresh .btn,.app.design-refresh .pill,.app.design-refresh .admin-menu button,.app.design-refresh .hub button{border-radius:10px;box-shadow:0 2px 0 rgba(58,20,16,.09)}
.app.design-refresh .avatar{box-shadow:0 0 0 3px var(--paper),0 0 0 4px var(--line),2px 3px 0 var(--maroon)}
.app.design-refresh .avatar.lg{box-shadow:0 0 0 4px var(--paper),0 0 0 5px var(--line),4px 5px 0 var(--maroon)}
.app.design-refresh .gantt{border:1px solid var(--line);box-shadow:0 6px 16px rgba(58,20,16,.06)}
.app.design-refresh .gr{transition:background-color .15s ease}
.app.design-refresh .bar{border-radius:999px;box-shadow:inset 0 1px rgba(255,255,255,.3);transition:filter .15s ease}
.app.design-refresh .metrics-member-link{transition:transform .15s ease,box-shadow .15s ease,background-color .15s ease}
.app.design-refresh .metrics-chart-panel .chart-member rect{transition:filter .15s ease}
.app.design-refresh .status-switch.on{box-shadow:0 0 0 3px rgba(181,71,42,.12)}
.app.design-refresh .status-switch:active .status-switch-track i{transform:scale(.86)}
@media(hover:hover){
  .app.design-refresh button:not(.back):not(.avatar):not(.bell):not(.chev):not(.rb):hover{transform:translateY(-1px);box-shadow:0 5px 12px rgba(58,20,16,.13)}
  .app.design-refresh .avatar:hover{transform:rotate(-4deg) scale(1.04)}
  .app.design-refresh .gr:hover{background-color:rgba(255,255,255,.3)}
  .app.design-refresh .chart-member:hover rect{filter:brightness(1.08)}
  .app.design-refresh .metrics-member-link:hover{transform:translateY(-1px);box-shadow:0 4px 10px rgba(58,20,16,.09)}
}
.app.design-refresh button:not(.back):not(.avatar):not(.bell):not(.chev):not(.rb){transition:transform .15s ease,box-shadow .15s ease,background-color .15s ease,color .15s ease}
.app.design-refresh .avatar{transition:transform .15s ease,background-color .15s ease}
@media(prefers-reduced-motion:reduce){.app.design-refresh *{transition:none!important;animation:none!important;scroll-behavior:auto!important}}
`;

const ini = (n) => n.split(" ").map((w) => w[0]).join("");
const IC = { back: "M15 5l-7 7 7 7", bell: "M6 17h12l-1.5-2V10a4.5 4.5 0 0 0-9 0v5zM10 20h4", mic: "M12 4a3 3 0 0 1 3 3v4a3 3 0 0 1-6 0V7a3 3 0 0 1 3-3zM6 11a6 6 0 0 0 12 0M12 17v3", check: "M5 12.5l4.5 4.5L19 7", x: "M6 6l12 12M18 6L6 18", chev: "M6 9l6 6 6-6", arrow: "M5 12h14M13 6l6 6-6 6" };
const Icon = ({ n, s = 22 }) => <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={IC[n]} /></svg>;
const Avatar = ({ p, cls = "", ...r }) => <button className={`avatar ${cls}`} title={p.name} aria-label={p.name} {...r}>{ini(p.name)}</button>;

/* ---------- Gantt ---------- */
function Gantt({ tasks: all, allTasks = all, isAdminView = false, showAll, onShowAllChange, onOpen, who: owner }) {
  const [deps, setDeps] = useState(false);
  const [hoveredTaskId, setHoveredTaskId] = useState(null);
  const [week, setWeek] = useState(0); // 0 = this week, -1 = last week, 1 = next week
  const H = 40, W = 700, cw = W / 7;
  // Live tasks carry a real due date: place each one on the selected week's Mon..Sun columns.
  // Sample tasks (no dueIso) keep their hand-set day/len.
  const dated = allTasks.some((t) => t.dueIso);
  const monday = weekStart();
  monday.setDate(monday.getDate() + 7 * week);
  const sunday = new Date(monday); sunday.setDate(monday.getDate() + 6);
  const fmt = (d) => d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  const weekTasks = (list) => !dated ? [...list].sort(compareByDueDate) : list
    .filter((t) => t.dueIso)
    .map((t) => ({ ...t, day: Math.round((new Date(`${t.dueIso}T00:00:00`) - monday) / 86400000), len: 1 }))
    .filter((t) => t.day >= 0 && t.day < 7)
    .sort(compareByDueDate);
  const baseTasks = weekTasks(isAdminView && showAll ? allTasks : all);
  const taskIds = new Set(baseTasks.map((t) => t.id));
  const ownTaskIds = new Set(weekTasks(all).map((t) => t.id));
  const weeklyAllTasks = weekTasks(allTasks);
  const getConnectedTaskIds = (rootIds, scopeTasks = weeklyAllTasks) => {
    const connected = new Set(rootIds);
    const scopeIds = new Set(scopeTasks.map((task) => task.id));
    const pending = [...rootIds];
    while (pending.length) {
      const currentId = pending.pop();
      scopeTasks.forEach((candidate) => {
        const neighbors = [];
        if (candidate.dep === currentId) neighbors.push(candidate.id);
        if (candidate.id === currentId && candidate.dep != null) neighbors.push(candidate.dep);
        neighbors.forEach((id) => {
          if (scopeIds.has(id) && !connected.has(id)) {
            connected.add(id);
            pending.push(id);
          }
        });
      });
    }
    return connected;
  };
  const linkedIds = deps ? getConnectedTaskIds([...taskIds]) : new Set();
  const hoverScope = isAdminView && showAll ? weeklyAllTasks : baseTasks;
  const highlightedIds = hoveredTaskId === null
    ? new Set() : getConnectedTaskIds([hoveredTaskId], hoverScope);
  const showLinkedTasks = deps || hoveredTaskId !== null;
  const chartTaskIds = new Set([...taskIds, ...linkedIds, ...highlightedIds]);
  const chartTasks = weeklyAllTasks.filter((t) => chartTaskIds.has(t.id)).sort(compareByDueDate);
  const idx = Object.fromEntries(chartTasks.map((t, i) => [t.id, i]));
  return (
    <div>
      {dated && <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 12, marginBottom: 6 }}>
        <button className="btn alt" style={{ padding: "4px 14px" }} aria-label="Previous week" onClick={() => setWeek(week - 1)}>◀</button>
        <b>{fmt(monday)} – {fmt(sunday)}{week === 0 ? " (this week)" : ""}</b>
        <button className="btn alt" style={{ padding: "4px 14px" }} aria-label="Next week" onClick={() => setWeek(week + 1)}>▶</button>
      </div>}
      <div className={`gantt-controls${isAdminView ? " admin-controls" : ""}`}>
        {isAdminView && (
          <button type="button" className="tog" aria-pressed={showAll} aria-label={`Gantt view: ${showAll ? "all E-board tasks" : "my tasks"}. Switch view.`}
            onClick={() => onShowAllChange((visible) => !visible)}>
            {showAll ? "All E-board tasks" : "My tasks"} <span className={`sw ${showAll ? "on" : ""}`} aria-hidden="true"><i /></span>
          </button>
        )}
        <button type="button" className="tog" aria-pressed={deps} onClick={() => setDeps((visible) => !visible)}>
          Show linked tasks <span className={`sw ${deps ? "on" : ""}`} aria-hidden="true"><i /></span>
        </button>
      </div>
      <div className="gantt">
        <div className="gh"><span>Task title</span><span>Priority</span><span>Start date</span><span>Due date</span><span>Date finished</span>
          <div className="days">{DAYS.map((d) => <span key={d}>{d}</span>)}</div></div>
        <div style={{ position: "relative" }}>
          {chartTasks.map((t) => {
            const isRelated = !taskIds.has(t.id);
            const isHighlighted = hoveredTaskId !== null && highlightedIds.has(t.id);
            const isDimmed = hoveredTaskId !== null && !isHighlighted;
            const ownerName = person(t.assignee)?.name;
            const showOwner = isRelated || (isAdminView && showAll && !ownTaskIds.has(t.id));
            const priority = t.priority ?? "normal";
            const priorityLabel = priority.charAt(0).toUpperCase() + priority.slice(1);
            return (
            <div className="gr" key={t.id} onClick={() => onOpen(t.id)}
              onMouseEnter={() => setHoveredTaskId(t.id)} onMouseLeave={() => setHoveredTaskId(null)}>
              <span title={showOwner ? `${t.title} — ${ownerName}` : t.title}>{t.title}{showOwner && ownerName ? ` · ${ownerName}` : ""}</span>
              <span className={`priority-${priority}`} title={`${priorityLabel} priority`}>{priorityLabel}</span>
              <span>{t.start.slice(0, 5)}</span><span>{t.due.slice(0, 5)}</span><span>{t.finished ? t.finished.slice(0, 5) : "—"}</span>
              <div className="lane"><div className={`bar${isRelated ? " related-bar" : ""}${isHighlighted ? " linked-highlight" : ""}${isDimmed ? " unrelated-dim" : ""}`}
                style={{ left: `${(t.day / 7) * 100}%`, width: `${(t.len / 7) * 100}%`, background: COLORS[t.status] }} /></div>
            </div>
            );
          })}
          {!baseTasks.length && <p style={{ textAlign: "center", padding: "18px 0", margin: 0 }}>
            No tasks due {owner ? `for ${owner} ` : ""}this week. Use ◀ ▶ to see other weeks.</p>}
          {showLinkedTasks && (
            <svg className="dependency-lines" viewBox={`0 0 ${W} ${chartTasks.length * H}`} preserveAspectRatio="none" style={{ height: chartTasks.length * H }}>
              {chartTasks.filter((t) => t.dep && idx[t.dep] !== undefined).map((t) => {
                const a = chartTasks.find((item) => item.id === t.dep), x1 = (a.day + a.len) * cw, y1 = idx[a.id] * H + H / 2, x2 = (t.day + 0.1) * cw, y2 = idx[t.id] * H + 9;
                return <path key={t.id} d={`M${x1} ${y1} H${x1 + 8} V${y2 - 4} H${x2} V${y2}`} fill="none" stroke="#4a1109" strokeWidth="1.6" vectorEffect="non-scaling-stroke" />;
              })}
            </svg>
          )}
        </div>
      </div>
      <div className="legend">{Object.entries(COLORS).map(([k, c]) => <span key={k}><i style={{ background: c }} />{k}</span>)}{deps && !showAll && <span><i className="related-swatch" />Related task</span>}{isAdminView && showAll && <span><i className="related-swatch" />Other E-board tasks</span>}</div>
    </div>
  );
}

/* ---------- App ---------- */
export default function App({ profile, admin, signOut }) {
  const [stack, setStack] = useState([{ n: "dash" }]);
  const [viewAs, setViewAs] = useState(null);
  const [adminShowAllGantt, setAdminShowAllGantt] = useState(false);
  const [modal, setModal] = useState(null);
  const [toast, setToast] = useState("");
  const [requestError, setRequestError] = useState("");
  const [requestBusy, setRequestBusy] = useState(false);
  const mutationLock = useRef(false);
  const [requestReason, setRequestReason] = useState("");
  const [dataError, setDataError] = useState("");
  const [loading, setLoading] = useState(true);
  const refreshVersion = useRef(0);
  const [planInput, setPlanInput] = useState(EMPTY_PLAN_INPUT);
  const [taskForm, setTaskForm] = useState(EMPTY_TASK_FORM);
  const [savedTaskForm, setSavedTaskForm] = useState(null);
  const [generatingPlan, setGeneratingPlan] = useState(false);
  const [submittingTask, setSubmittingTask] = useState(false);
  const [planError, setPlanError] = useState("");
  const [reqs, setReqs] = useState(REQUESTS);
  const [reassignmentReason, setReassignmentReason] = useState("");
  const [attendanceByMeeting, setAttendanceByMeeting] = useState(() =>
    Object.fromEntries(MEETINGS.map((meeting) => [meeting.id, meeting.attendees])),
  );
  const [attendanceMeetingId, setAttendanceMeetingId] = useState(MEETINGS[0]?.id ?? "");
  const [profileDrafts, setProfileDrafts] = useState({});
  const [open, setOpen] = useState({});
  const [notes, setNotes] = useState({});
  const [recorder, setRecorder] = useState(null); // meeting kind being recorded, or null
  const [cands, setCands] = useState({}); // task id -> {loading} | {list} | {error}: skill-matched suggestions
  const loadCandidates = (t) => {
    setCands((c) => ({ ...c, [t.id]: { loading: true } }));
    getCandidates(t.id)
      .then((list) => setCands((c) => ({ ...c, [t.id]: { list } })))
      .catch((e) => setCands((c) => ({ ...c, [t.id]: { error: e.message } })));
  };
  const [TASKS, setTasks] = useState([]);
  const [PEOPLE, setPeople] = useState([]);
  const tasks = TASKS; // the redesign's screens read `tasks`; same live list
  const [source, setSource] = useState("Loading tasks…");
  const live = source.startsWith("Live");
  currentTasks = TASKS;
  currentPeople = PEOPLE;
  const refresh = useCallback(async () => {
    const version = ++refreshVersion.current;
    try {
      const [ts, people, assignments, requests] = await Promise.all([
        getTasks(), getMembers(), getAssignments(), requestsStore.list(),
      ]);
      if (version !== refreshVersion.current) return;
      const byTask = assignments.byTask;
      setTasks(ts.map((t) => {
        const codes = t.ownerCode ? [t.ownerCode] : byTask[t.id] ?? [];
        return { ...t, assignees: codes, assignee: codes[0] ?? null };
      }));
      setPeople(people);
      setReqs(requests);
      setDataError("");
      setSource(`Live: ${ts.length} tasks, ${people.length} members`);
    } catch (e) {
      if (version === refreshVersion.current) {
        setDataError(e.message);
        setSource("Connection error ? displayed data may be out of date");
      }
      throw e;
    } finally { if (version === refreshVersion.current) setLoading(false); }
  }, []);
  useEffect(() => {
    Promise.all([getTasks(), getMembers(), getAssignments().catch(() => null)])
      .then(([ts, people, assignments]) => {
        const byTask = assignments?.byTask ?? {};
        // First recognized member is the "assignee" the design shows; all of them can see the task.
        setTasks(ts.map((t) => {
          const assignees = t.currentAssignee ? [t.currentAssignee] : byTask[t.id] ?? [];
          return { ...t, assignees, assignee: t.currentAssignee ?? assignees[0] ?? null };
        }));
        if (people.length) setPeople(people);
        const linked = Object.values(byTask).filter((c) => c && c.length).length;
        setSource(`Live: ${ts.length} tasks, ${people.length} members, ${linked} tasks linked to people`);
      })
      .catch((e) => setSource(`Sample data (${e.message})`));
  }, []);
  useEffect(() => {
    const reload = () => { refresh().catch(() => {}); };
    reload();
    const timer = setInterval(reload, 15000);
    window.addEventListener("focus", reload);
    return () => { ++refreshVersion.current; clearInterval(timer); window.removeEventListener("focus", reload); };
  }, [refresh]);
  useEffect(() => { if (!admin) setViewAs(null); }, [admin]);
  const sendRequest = async () => {
    if (mutationLock.current || !modal?.reassign) return;
    mutationLock.current = true; setRequestBusy(true); setRequestError("");
    try {
      await requestsStore.submit(modal.reassign[0].id, modal.reassign[1].id, requestReason);
      setModal(null); setRequestReason("");
      say("Reassignment request saved for review");
      try { await refresh(); } catch { say("Request saved. Refresh failed; please retry."); }
    } catch (e) { setRequestError(e.message); }
    finally { mutationLock.current = false; setRequestBusy(false); }
  };
  const decideRequest = async (r, decision) => {
    if (mutationLock.current || !admin) return;
    mutationLock.current = true; setRequestBusy(true); setRequestError("");
    try {
      await requestsStore.review(r.id, decision);
      setCands({});
      say(decision === "approved" ? "Approved ? task assignment saved" : "Request denied");
      try { await refresh(); } catch { say("Decision saved. Refresh failed; please retry."); }
    } catch (e) {
      setRequestError(e.message);
      refresh().catch(() => {});
    } finally { mutationLock.current = false; setRequestBusy(false); }
  };
  const changeStatus = async (t, status) => {
    if (!live) { say("Reconnect and refresh before saving changes"); return; }
    try {
      await updateTaskStatus(t.id, status);
      await refresh();
      say(`Saved: ?${t.title}? is ${status}`);
    } catch (e) { say(`Could not refresh or save: ${e.message}`); }
  };
  const p = stack[stack.length - 1];
  const go = (n, x = {}) => setStack((s) => [...s, { n, ...x }]);
  const back = () => setStack((s) => (s.length > 1 ? s.slice(0, -1) : s));
  const say = (m) => { setToast(m); setTimeout(() => setToast(""), 2400); };
  const sendReassignmentRequest = () => {
    const [targetTask, targetMember] = modal.reassign;
    const reason = reassignmentReason.trim();
    if (!reason || /[\r\n]/.test(reason) || /[.!?]\s+\S/.test(reason)) {
      say("Enter a one-sentence reason on a single line.");
      return;
    }
    if (live) {
      say("Reassignment requests are not connected to the backend yet; nothing was saved.");
      return;
    }
    setReqs((current) => [{
      id: Date.now(),
      task: targetTask.id,
      from: me.id,
      to: targetMember.id,
      reason,
      status: "pending",
      requestedAt: new Date().toLocaleDateString(),
    }, ...current]);
    setModal(null);
    setReassignmentReason("");
    say("Request added to sample data for this session only.");
  };
  const reviewReassignmentRequest = (requestId, decision) => {
    if (live) {
      say("Reassignment reviews are not connected to the backend yet; nothing was changed.");
      return;
    }
    const reviewedRequest = reqs.find((request) => request.id === requestId);
    if (decision === "approved" && reviewedRequest) {
      setTasks((current) => current.map((item) => item.id === reviewedRequest.task
        ? { ...item, assignee: reviewedRequest.to, currentAssignee: reviewedRequest.to, assignees: [reviewedRequest.to] }
        : item));
    }
    setReqs((current) => current.map((request) =>
      request.id === requestId ? { ...request, status: decision } : request,
    ));
    say(`Request ${decision} in sample data for this session only.`);
  };
  const saveMeetingAttendance = () => {
    if (live) {
      say("Meeting attendance is not connected to the backend yet; nothing was saved.");
      return;
    }
    say("Attendance updated in sample data for this session only.");
  };
  const openTaskCreator = (form, generated = false) => {
    const initialForm = { ...form };
    setTaskForm(initialForm);
    setSavedTaskForm(initialForm);
    go("createTask", { initialForm, generated });
  };
  const enterTaskManually = () => openTaskCreator({
    ...EMPTY_TASK_FORM,
    title: planInput.name.trim(),
    description: planInput.description,
    startDate: planInput.startDate,
    dueDate: planInput.dueDate,
    time: planInput.time,
  });
  const generateTask = async () => {
    const name = planInput.name.trim(), description = planInput.description.trim();
    if (!name || !description || !planInput.dueDate) {
      setPlanError("Enter a task name, description, and due date before generating.");
      return;
    }
    if (planInput.startDate && planInput.startDate > planInput.dueDate) {
      setPlanError("The start date must be on or before the due date.");
      return;
    }
    setGeneratingPlan(true);
    setPlanError("");
    try {
      const idea = [
        description,
        planInput.startDate ? `Requested start date: ${planInput.startDate}` : "",
        planInput.time ? `Requested time: ${planInput.time}` : "",
      ].filter(Boolean).join("\n\n");
      const draft = await generateTaskPlan({
        event_name: name,
        idea,
        event_type: "WiCS",
        event_date: planInput.dueDate,
        event_format: "other",
      });
      if (!Array.isArray(draft.tasks) || !draft.tasks.length) {
        throw new Error("The planner returned no task suggestions.");
      }
      const titleById = Object.fromEntries(draft.tasks.map((t) => [t.id, t.title]));
      const generatedSummary = [
        draft.tasks.map((t, i) => {
          const due = t.due_date ? ` · due ${t.due_date}` : "";
          const role = t.suggested_role ? ` · suggested role: ${t.suggested_role}` : "";
          const dependencies = (t.dependency_ids ?? []).map((id) => titleById[id] ?? id);
          return [
            `${i + 1}. ${t.title}${due}${role}`,
            t.rationale,
            dependencies.length ? `Depends on: ${dependencies.join(", ")}` : "",
          ].filter(Boolean).join("\n");
        }).join("\n\n"),
        draft.questions?.length ? `Questions to review:\n${draft.questions.map((q) => `• ${q}`).join("\n")}` : "",
        draft.warnings?.length ? `Planning notes:\n${draft.warnings.map((w) => `• ${w}`).join("\n")}` : "",
      ].filter(Boolean).join("\n\n");
      openTaskCreator({
        ...EMPTY_TASK_FORM,
        title: name,
        description: planInput.description,
        startDate: planInput.startDate,
        dueDate: planInput.dueDate,
        time: planInput.time,
        summary: generatedSummary,
      }, true);
    } catch (e) {
      setPlanError(`Could not generate the task plan: ${e.message}`);
    } finally {
      setGeneratingPlan(false);
    }
  };
  const saveTaskDraft = () => {
    setSavedTaskForm({ ...taskForm });
    say("Draft saved for this session.");
  };
  const submitTask = async () => {
    const title = taskForm.title.trim();
    const monthSource = taskForm.dueDate || taskForm.startDate;
    if (!title) { say("Enter a task name before submitting."); return; }
    if (!monthSource) { say("Enter a start date or due date."); return; }
    if (taskForm.startDate && taskForm.dueDate && taskForm.startDate > taskForm.dueDate) {
      say("The start date must be on or before the due date.");
      return;
    }
    if (!live) { say("Sample data: connect task storage to submit tasks."); return; }
    const description = [
      taskForm.description.trim(),
      taskForm.startDate ? `Start date: ${taskForm.startDate}` : "",
      taskForm.time ? `Time: ${taskForm.time}` : "",
      taskForm.summary.trim() ? `Task summary:\n${taskForm.summary.trim()}` : "",
    ].filter(Boolean).join("\n\n");
    if (description.length > 10000) { say("Task details must be 10,000 characters or fewer."); return; }
    setSubmittingTask(true);
    try {
      const created = await createTaskRecord({
        title,
        month_code: monthSource.slice(0, 7),
        description,
        due_date: taskForm.dueDate || null,
        priority: taskForm.priority,
        status: "todo",
      });
      const taskRecord = {
        ...created,
        start: uiDate(taskForm.startDate) || created.start,
        notes: description,
      };
      setTasks((current) => [taskRecord, ...current]);
      say(`Created “${title}”.`);
      setStack([{ n: "dash" }, { n: "task", id: taskRecord.id }]);
    } catch (e) {
      say(`Task was not created: ${e.message}`);
    } finally {
      setSubmittingTask(false);
    }
  };
  // Status buttons in the redesign: save through the same path as the task page.
  const setTaskStatus = (id, status) => { const t = task(id); if (t) changeStatus(t, status); };
  const isAdminView = admin && !viewAs;
  // No real login yet: admins see the President's view, everyone else the Vice President's.
  const byRole = (role) => PEOPLE.find((q) => q.role === role);
  const me = (viewAs ? person(viewAs) : live ? byRole(isAdminView ? "President" : "Vice President") : person(isAdminView ? 1 : 2)) ?? PEOPLE[0];
  const sameMember = (left, right) => left != null && right != null && String(left) === String(right);
  const currentOwner = (t) => t.currentAssignee ?? t.current_assignee_code ?? t.assignee;
  const initialOwner = (t) => t.initialAssignee ?? t.initial_assignee_code ?? t.owner_code;
  const isOverdue = (t) => {
    if (t.status === "Completed") return false;
    const dueIso = t.dueIso ?? (/^\d{2}\/\d{2}\/\d{4}$/.test(t.due || "")
      ? `${t.due.slice(6, 10)}-${t.due.slice(0, 2)}-${t.due.slice(3, 5)}` : "");
    const today = new Date();
    const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    return Boolean(dueIso && dueIso < todayIso);
  };
  const getMemberStatus = (member) => {
    const memberTasks = TASKS.filter((t) => owns(t, member.id));
    const transferRequests = live ? [] : reqs;
    const transferredRequestTasks = new Set(transferRequests
      .filter((request) => request.status === "approved" && sameMember(request.to, member.id))
      .map((request) => String(request.task)));
    const isTransferred = (t) => sameMember(currentOwner(t), member.id) &&
      ((initialOwner(t) != null && !sameMember(initialOwner(t), currentOwner(t))) ||
        transferredRequestTasks.has(String(t.id)));
    const completed = memberTasks.filter((t) => t.status === "Completed");
    const transferred = memberTasks.filter((t) => t.status !== "Completed" && isTransferred(t));
    const overdue = memberTasks.filter((t) => t.status !== "Completed" && !isTransferred(t) && isOverdue(t));
    const pending = memberTasks.filter((t) => t.status !== "Completed" && !isTransferred(t) && !isOverdue(t));
    return { completed, pending, overdue, transferred };
  };
  const getReassignmentCounts = (member) => {
    const requests = live ? [] : reqs;
    return {
      requested: requests.filter((request) => sameMember(request.from, member.id)).length,
      approved: requests.filter((request) => request.status === "approved" && sameMember(request.from, member.id)).length,
      received: requests.filter((request) => request.status === "approved" && sameMember(request.to, member.id)).length,
    };
  };

  const Top = ({ title, tag, noBack }) => (
    <div className="top">
      {noBack ? <span className="sp" /> : <button className="back" onClick={back} aria-label="Back"><Icon n="back" /></button>}
      <h1>{title}</h1>{tag ? <span className="adm">(ADMIN)</span> : <span className="sp" />}
    </div>
  );
  const Ident = ({ q, sub }) => (
    <div className="id"><Avatar p={q} cls="lg" tabIndex={-1} /><div><h2>{q.name}</h2><p>{q.role}</p></div></div>
  );
  const Grid = ({ title, tag, onPick, extra, description }) => (
    <>
      <Top title={title} tag={tag} />
      {description && <p className="grid-intro">{description}</p>}
      <div className="grid2"><div className="divider" style={{ gridRow: `1/${Math.ceil(PEOPLE.length / 2) + 1}` }} />
        {PEOPLE.map((q, i, all) => (
          <div className="row" key={q.id} style={{ gridColumn: i < Math.ceil(all.length / 2) ? 1 : 3, gridRow: (i % Math.ceil(all.length / 2)) + 1 }}>
            <Avatar p={q} onClick={() => onPick(q)} /><button className="pill" onClick={() => onPick(q)}>{q.name} | {q.role}</button>
          </div>
        ))}
      </div>
      {extra}
    </>
  );
  const Nav = () => (
    <div className="nav"><button onClick={() => go("meetings")}>Meetings</button><button onClick={() => go("tasks")}>Tasks</button><button onClick={() => go("profiles")}>Profiles</button></div>
  );

  let page;
  const adminPages = ["admin", "editlist", "edit", "eval", "evals", "taskmetrics", "tm", "meetmetrics", "mm", "reassigned"];
  switch (!admin && adminPages.includes(p.n) ? "dash" : p.n) {
    case "dash": {
      // Live: the Gantt picks the week itself; admins see everyone's tasks, members their own.
      const mine = TASKS.filter((t) => owns(t, me.id));
      const pending = TASKS.filter((t) => t.status !== "Completed");
      const soon = (live ? [...pending].sort((a, b) => (a.dueIso ?? "9999").localeCompare(b.dueIso ?? "9999")) : pending).slice(0, isAdminView ? 3 : 4);
      page = (<>
        <div className="top"><h1 className="greeting">Hey {me.name.split(" ")[0]}!</h1>
          {viewAs ? <button className="btn alt" onClick={() => { setViewAs(null); setStack([{ n: "dash" }, { n: "admin" }]); }}>BACK TO ADMIN</button>
            : isAdminView ? <button className="btn alt" onClick={() => go("admin")}>ADMIN SETTINGS</button>
            : <button className="bell" aria-label="Notifications" onClick={() => go("review")}><Icon n="bell" s={26} /><b>{reqs.filter(r => r.status === "pending").length}</b></button>}
          <Avatar p={me} onClick={() => go("profile", { id: me.id })} /></div>
        <div className="home"><div><h3>Your Gantt Chart:</h3><Gantt tasks={mine} allTasks={TASKS} isAdminView={isAdminView} showAll={adminShowAllGantt} onShowAllChange={setAdminShowAllGantt} who={live && !isAdminView ? me.name : null} onOpen={(id) => go("task", { id })} /></div>
          <div><h3>Due Soon:</h3>{soon.map((t) => (<div className="due" key={t.id}>
            {isAdminView && <Avatar p={who(t)} cls="sm" onClick={() => t.assignee && go("profile", { id: t.assignee })} />}
            <button className="pill due-task" title={t.title} onClick={() => go("task", { id: t.id })}>{t.title}</button>
            {t.status === "Upcoming"
              ? <button className="btn alt status-action" aria-label={`Start ${t.title}`} onClick={() => setTaskStatus(t.id, "In-Progress")}>Start</button>
              : <button type="button" role="switch" className={`status-switch ${t.status === "Completed" ? "on" : ""}`}
                aria-checked={t.status === "Completed"}
                aria-label={`Mark ${t.title} ${t.status === "Completed" ? "in progress" : "completed"}`}
                onClick={() => setTaskStatus(t.id, t.status === "Completed" ? "In-Progress" : "Completed")}>
                <span className="status-switch-track" aria-hidden="true"><i /></span>
                {t.status === "Completed" ? "Completed" : "In progress"}
              </button>}
          </div>))}</div></div>
      </>);
      break;
    }
    case "meetings":
      page = (<><Top title="Meetings" /><div style={{ textAlign: "right", marginTop: -50, marginBottom: 20, fontSize: 20, pointerEvents: "none" }}>11/14/2026</div>
        <div className="two meeting-layout" style={{ gridTemplateColumns: "180px 1fr", gap: 24 }}>
          <div className="side panel">{["Internal", "Committee", "External"].map((k) => <button key={k} className="pill" onClick={() => setRecorder(k)}>{k}</button>)}</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
            {["Internal", "Committee", "External"].map((k) => <button key={k} className="pill" style={{ padding: 28, display: "flex", alignItems: "center", gap: 10 }} onClick={() => setRecorder(k)}><Icon n="mic" />Create a new {k.toLowerCase()} recording</button>)}
            <button className="btn alt" style={{ alignSelf: "flex-end" }} onClick={() => go("past")}>Past Meetings</button></div></div></>);
      break;
    case "past":
      page = (<><Top title="Your past meetings" /><table style={{ borderCollapse: "collapse", width: "100%", maxWidth: 900, margin: "20px auto", background: "#fff", borderRadius: 16, overflow: "hidden" }}>
        <thead><tr style={{ background: "var(--panel)", fontSize: 24 }}><th style={{ padding: 14, width: 200 }}>Date</th><th>Access</th></tr></thead>
        <tbody>{MEETINGS.map((m) => <tr key={m.id}><td style={{ background: "var(--panel)", textAlign: "center", padding: 18, fontSize: 18 }}>{m.date}</td><td style={{ padding: 10 }}><button className="pill" style={{ width: "100%", textAlign: "center" }} onClick={() => go("meeting", { id: m.id })}>{m.name}</button></td></tr>)}</tbody></table></>);
      break;
    case "meeting": {
      const m = MEETINGS.find((x) => x.id === p.id);
      page = (<><Top title={m.name} /><p style={{ textAlign: "center", margin: "0 0 18px", fontSize: 20 }}>{m.date}</p>
        <div className="cols"><div className="panel"><h3>Notes:</h3><p>{"• Reviewed GBM 1 timeline\n• Confirmed budget owner\n• Flyer due before Thursday\n• Next meeting TBD"}</p></div>
          <div className="panel"><h3>Transcript:</h3><p>{"[00:00] Welcome everyone…\n[00:42] First item is the GBM agenda…\n[03:10] Who can take the budget?…"}</p></div>
          <div><h3 style={{ textAlign: "center", fontSize: 24, marginTop: 0 }}>Delegated Tasks:</h3>
            {m.tasks.map(([t, a]) => <div className="due" key={t}><Icon n="arrow" s={18} /><button className="pill" style={{ flex: 1, textAlign: "center" }} onClick={() => go("task", { id: TASKS.find((x) => x.title === t)?.id || 1 })}>{t}<br /><small>Assignee: {person(a)?.name || "Not linked"}</small></button></div>)}</div></div></>);
      break;
    }
    case "profiles":
      page = <Grid title="Profiles" onPick={(q) => go("profile", { id: q.id })} />;
      break;
    case "profile": {
      const q = person(p.id) ?? me, ts = TASKS.filter((t) => owns(t, q.id));
      page = (<><Top title="Profile" tag={isAdminView} />
        <div className="id"><Avatar p={q} cls="lg" tabIndex={-1} /><div><h2 style={isAdminView ? { cursor: "pointer" } : {}} onClick={() => isAdminView && setModal({ view: q })}>{q.name}</h2><p>{q.role}</p></div></div>
        <div className="two"><div className="panel"><h3>Tasks</h3><ul>{ts.map((t) => <li key={t.id}><a href="#t" onClick={(e) => { e.preventDefault(); go("task", { id: t.id }); }}>{t.title}</a> ({t.status})</li>)}{!ts.length && <li className="none">No tasks assigned yet.</li>}</ul></div>
          <div className="panel"><h3>Skills</h3>
            {q.technical?.length || q.soft?.length ? (<>
              <p className="lbl" style={{ margin: "4px 0" }}>Technical</p><ul>{q.technical.map((s) => <li key={s}>{s}</li>)}</ul>
              <p className="lbl" style={{ margin: "8px 0 4px" }}>Soft skills</p><ul>{q.soft.map((s) => <li key={s}>{s}</li>)}</ul>
              {q.skillsSource === "role-derived" && <p style={{ fontSize: 13, opacity: 0.75 }}>Based on the {q.role} role description, not individual experience.</p>}
            </>) : <ul>{q.skills.map((s) => <li key={s}>{s}</li>)}{!q.skills.length && <li>No skills listed yet</li>}</ul>}
            {q.description && <p style={{ fontSize: 15, lineHeight: 1.5 }}>{q.description}</p>}</div></div>
          <div className="panel" style={{ marginTop: 18 }}><h3>Previous Roles</h3>
            {q.previousRoles?.length ? <ul>{q.previousRoles.map((role) => <li key={role}>{role}</li>)}</ul> : <p className="metrics-note">No previous roles recorded.</p>}
            {q.previousRoleSkills?.length > 0 && <><h4>Skills from Previous Roles</h4><ul>{q.previousRoleSkills.map((skill) => <li key={skill}>{skill}</li>)}</ul></>}
          </div></>);
      break;
    }
    case "task": {
      const t = task(p.id);
      if (!t) { page = (<><Top title="Task not found" /><p style={{ textAlign: "center", fontSize: 20 }}>This task isn’t in the current data (meeting links still use sample tasks).</p></>); break; }
      const dep = t.dep ? task(t.dep) : null;
      const currentAssigneeId = currentOwner(t);
      const initialAssigneeId = initialOwner(t);
      const rows = [["Date assigned", t.assigned], ["Start date", t.start], ["Due date", t.due],
        ["Initial assignee", initialAssigneeId ? person(initialAssigneeId)?.name ?? "Not recorded" : t.assigneeText || "Not recorded"],
        ["Current assignee", currentAssigneeId ? person(currentAssigneeId)?.name ?? "Not recorded" : t.assigneeText || "Not recorded"],
        ["Status", t.status], ["Dependency", dep ? `Depends on “${dep.title}” (${who(dep).name})` : "None"]];
      page = (<><Top title={t.title} /><div className="two" style={{ maxWidth: 960, margin: "10px auto" }}>
        <div className="panel">
          {t.status !== "Completed" && <label>Request reassignment to
            <select className="field" value="" disabled={!live || !profile.member_code} onChange={e => {
              const proposed = person(e.target.value);
              if (proposed) { setRequestError(""); setRequestReason(""); setModal({ reassign: [t, proposed] }); }
            }}><option value="">Choose a member</option>
              {PEOPLE.filter(q => !owns(t, q.id)).map(q => <option key={q.id} value={q.id}>{q.name}</option>)}
            </select>
          </label>}
          <div className="form task-form" style={{ textAlign: "left", fontSize: 18 }}>
          {rows.map(([k, v]) => [<span className="lbl" key={k}>{k}:</span>, k === "Status" ? <select key="s" className="field" value={v} onChange={(e) => changeStatus(t, e.target.value)}>{Object.keys(COLORS).map((s) => <option key={s}>{s}</option>)}</select> : <span key={k + 1}>{v}</span>])}</div></div>
        <div className="panel"><h3>Notes</h3><textarea className="field" style={{ minHeight: 200 }} placeholder="Add notes for yourself or an admin…" value={notes[t.id] ?? t.notes} onChange={(e) => setNotes({ ...notes, [t.id]: e.target.value })} />
          <div style={{ textAlign: "center", marginTop: 12 }}><button className="btn" onClick={() => say("Notes saved (placeholder)")}>Save notes</button></div></div></div></>);
      break;
    }
    case "tasks": {
      const visibleTasks = isAdminView ? tasks : tasks.filter((t) => owns(t, me.id));
      const G = (title, st, avs) => (<>
        <h2 className="sec" style={{ gridColumn: 1 }}>{title}</h2>{avs ? <h2 className="sec" style={{ fontSize: 24 }}>Assign Task:</h2> : <span />}
        {visibleTasks.filter((t) => t.status === st).sort(compareByDueDate).map((t) => (<Fragment key={t.id}>
          <div className="pill" onClick={() => go("task", { id: t.id })}><span>{t.title} - {t.due}</span>
            <button className={`chev ${open[t.id] ? "open" : ""}`} aria-label="Expand" onClick={(e) => { e.stopPropagation(); setOpen({ ...open, [t.id]: !open[t.id] }); }}><Icon n="chev" s={20} /></button></div>
          <div className="row" style={{ gap: 8 }}>
            {isAdminView && <button type="button" className="btn alt" style={{ padding: "6px 14px", fontSize: 14 }}
              aria-label={`Nudge assignee for ${t.title}`}
              title={t.status === "Completed" ? "Completed tasks do not need a reminder" : "Notification delivery is not connected yet"}
              disabled={t.status === "Completed" || !t.assignee}
              onClick={(e) => { e.stopPropagation(); say("Nudge delivery is not connected yet; no reminder was sent."); }}>
              Nudge
            </button>}
            {avs && (live ? (() => {
            // Live: only people whose skills fit this task (backend + Gemini), lightest workload first.
            const c = cands[t.id];
            if (!c) return <button className="btn alt" style={{ padding: "6px 14px", fontSize: 14 }} title="Find board members whose skills fit this task" onClick={() => loadCandidates(t)}>Suggest</button>;
            if (c.loading) return <small>Checking skills…</small>;
            if (c.error) return <small title={c.error}>Couldn’t check · <a href="#retry" onClick={(e) => { e.preventDefault(); loadCandidates(t); }}>retry</a></small>;
            if (!c.list.length) return <small>No one else has the skills for this</small>;
            return c.list.map((s) => { const q = person(s.code) ?? { id: s.code, name: s.name };
              return <Avatar key={s.code} p={q} cls="sm" title={`${s.name} · ${s.fit === "strong" ? "Strong fit" : "Possible fit"}\n${s.matched_skills.join(", ")}\n${s.due_this_week} due this week · ${s.open} open\n${s.reason}`}
                style={s.fit === "strong" ? undefined : { opacity: 0.7 }} onClick={() => { setRequestError(""); setRequestReason(""); setModal({ reassign: [t, q, s] }); }} />; });
          })() : <small>Reconnect to request reassignment.</small>)}</div>
          {open[t.id] && <div className="det">Assignee: {t.assigneeText || who(t).name} · Status: {t.status} · Assigned {t.assigned}{t.event ? ` · ${t.event}` : ""}</div>}</Fragment>))}{!tasks.some((t) => t.status === st) && <p className="empty">Nothing here yet. Tasks move here as their status changes.</p>}</>);
      page = (<><Top title="Tasks Summary" /><div className="sum">{G("Due soon:", "Upcoming", 1)}{G("In progress:", "In-Progress", 1)}{G("Completed:", "Completed", 0)}</div></>);
      break;
    }
    case "planTask":
      page = (<><Top title="Plan with Winnie" tag />
        <div className="plan-task-form">
          <label className="wide">Task Name
            <input className="field" maxLength={200} value={planInput.name}
              onChange={(e) => { setPlanInput({ ...planInput, name: e.target.value }); setPlanError(""); }} />
          </label>
          <label className="wide">Task Description
            <textarea className="field" maxLength={6000} rows={4} value={planInput.description}
              onChange={(e) => { setPlanInput({ ...planInput, description: e.target.value }); setPlanError(""); }} />
          </label>
          <div className="wide plan-task-dates">
            <label>Start Date
              <input className="field" type="date" value={planInput.startDate}
                onChange={(e) => { setPlanInput({ ...planInput, startDate: e.target.value }); setPlanError(""); }} />
            </label>
            <label>Due Date
              <input className="field" type="date" value={planInput.dueDate}
                onChange={(e) => { setPlanInput({ ...planInput, dueDate: e.target.value }); setPlanError(""); }} />
            </label>
            <label>Time
              <input className="field" type="time" value={planInput.time}
                onChange={(e) => { setPlanInput({ ...planInput, time: e.target.value }); setPlanError(""); }} />
            </label>
          </div>
        </div>
        {planError && <p className="plan-error" role="alert">{planError}</p>}
        <div className="plan-task-actions">
          <button className="btn" type="button" disabled={generatingPlan} onClick={generateTask}>
            {generatingPlan ? "Generating…" : "Generate"}
          </button>
          <button className="btn alt" type="button" disabled={generatingPlan} onClick={enterTaskManually}>Enter Manually</button>
        </div></>);
      break;
    case "createTask": {
      const initialForm = p.initialForm ?? EMPTY_TASK_FORM;
      page = (<><Top title="Create a Task" tag />
        <div className="create-task-grid">
          <div className="panel"><div className="create-task-fields">
            <label>Name
              <input className="field" maxLength={200} value={taskForm.title}
                onChange={(e) => setTaskForm({ ...taskForm, title: e.target.value })} />
            </label>
            <label>Description
              <textarea className="field" maxLength={10000} value={taskForm.description}
                onChange={(e) => setTaskForm({ ...taskForm, description: e.target.value })} />
            </label>
            <label>Start Date
              <input className="field" type="date" value={taskForm.startDate}
                onChange={(e) => setTaskForm({ ...taskForm, startDate: e.target.value })} />
            </label>
            <label>End Date
              <input className="field" type="date" value={taskForm.dueDate}
                onChange={(e) => setTaskForm({ ...taskForm, dueDate: e.target.value })} />
            </label>
            <label>Time
              <input className="field" type="time" value={taskForm.time}
                onChange={(e) => setTaskForm({ ...taskForm, time: e.target.value })} />
            </label>
            <label>Priority
              <select className="field" value={taskForm.priority}
                onChange={(e) => setTaskForm({ ...taskForm, priority: e.target.value })}>
                <option value="low">Low</option><option value="normal">Normal</option><option value="high">High</option>
              </select>
            </label>
          </div></div>
          <div className="panel">
            <label>Task Summary
              <textarea className="field task-summary" maxLength={10000} value={taskForm.summary}
                placeholder="Winnie’s generated plan appears here. You can edit it before submitting."
                onChange={(e) => setTaskForm({ ...taskForm, summary: e.target.value })} />
            </label>
            {p.generated && <p style={{ marginBottom: 0, color: "var(--muted)" }}>Generated suggestions are a draft. Review and edit before submitting.</p>}
          </div>
        </div>
        <div className="create-task-actions">
          <button className="btn alt" type="button" onClick={() => setTaskForm({ ...(savedTaskForm ?? initialForm) })}>Revert Changes</button>
          <button className="btn out" type="button" onClick={saveTaskDraft}>Save Draft</button>
          <button className="btn" type="button" disabled={submittingTask} onClick={submitTask}>
            {submittingTask ? "Submitting…" : "Submit"}
          </button>
        </div></>);
      break;
    }
    case "admin":
      page = (<><Top title="Admin Settings" tag noBack /><div className="admin-menu">
        <button onClick={() => go("editlist")}>Edit Profiles</button>
        <button onClick={() => go("metricsOverview")}>Metrics Overview</button>
        <button onClick={() => go("review")}>Task Reassignment Requests</button>
        <button onClick={() => go("attendance")}>Manage Meeting Attendance</button>
        <button onClick={() => { setPlanInput({ ...EMPTY_PLAN_INPUT }); setPlanError(""); go("planTask"); }}>Create Task</button>
      </div>
        <div style={{ textAlign: "center" }}><button className="btn alt" onClick={() => setStack([{ n: "dash" }])}>Back to dashboard</button></div></>);
      break;
    case "metricsOverview": {
      const memberMetrics = PEOPLE.map((member) => ({ member, ...getMemberStatus(member) }));
      const maxTasks = Math.max(1, ...memberMetrics.map(({ completed, pending, overdue, transferred }) =>
        completed.length + pending.length + overdue.length + transferred.length,
      ));
      const chartYMax = Math.max(2, maxTasks + (maxTasks % 2 ? 1 : 2));
      const chartTickStep = chartYMax <= 4 ? 1 : 2;
      const chartWidth = Math.max(360, memberMetrics.length * 34 + 40);
      const chartLeft = 30, chartRight = 10, chartTop = 8, chartPlotHeight = 300, chartBaseline = chartTop + chartPlotHeight;
      const chartViewBoxHeight = 380;
      const chartStep = (chartWidth - chartLeft - chartRight) / Math.max(1, memberMetrics.length);
      const chartBarWidth = Math.min(18, chartStep * 0.62);
      const chartTicks = Array.from({ length: chartYMax / chartTickStep + 1 }, (_, index) => index * chartTickStep);
      page = (<><Top title="Metrics Overview" tag />
        <div className="metrics-overview">
          <div className="panel metrics-chart-panel">
            <h2>Overall Task Metrics</h2>
            <div className="metrics-legend">
              {[["Completed", "#7a2c22"], ["Pending", "#cc6a3d"], ["Overdue", "#ff8b4e"], ["Reassigned", REASSIGNED_COLOR]]
                .map(([label, color]) => <span key={label}><i style={{
                  background: color,
                  border: label === "Reassigned" ? "1px solid var(--line)" : undefined,
                }} />{label}</span>)}
            </div>
            <div className="metrics-chart-scroll">
              <svg className="task-metrics-chart" viewBox={`0 0 ${chartWidth} ${chartViewBoxHeight}`} role="img"
                aria-label={`Stacked task status counts by member, scale 0 to ${chartYMax}`} preserveAspectRatio="xMinYMin meet">
                {chartTicks.map((tick) => {
                  const y = chartBaseline - tick / chartYMax * chartPlotHeight;
                  return <g key={tick}>
                    <line x1={chartLeft} x2={chartWidth - chartRight} y1={y} y2={y} stroke="#aab8c1" strokeWidth="1" />
                    <text x={chartLeft - 7} y={y + 3} textAnchor="end" fontSize="10">{tick}</text>
                  </g>;
                })}
                <line x1={chartLeft} x2={chartLeft} y1={chartTop} y2={chartBaseline} stroke="#778891" strokeWidth="1" />
                <line x1={chartLeft} x2={chartWidth - chartRight} y1={chartBaseline} y2={chartBaseline} stroke="#778891" strokeWidth="1" />
                {memberMetrics.map(({ member, completed, pending, overdue, transferred }, index) => {
                  const segments = [
                    ["Completed", completed.length, "#7a2c22"],
                    ["Pending", pending.length, "#cc6a3d"],
                    ["Overdue", overdue.length, "#ff8b4e"],
                    ["Reassigned", transferred.length, REASSIGNED_COLOR],
                  ];
                  const total = segments.reduce((sum, [, count]) => sum + count, 0);
                  const center = chartLeft + chartStep * (index + 0.5);
                  let y = chartBaseline;
                  const bars = segments.map(([label, count, color]) => {
                    const height = count / chartYMax * chartPlotHeight;
                    y -= height;
                    return <rect key={label} x={center - chartBarWidth / 2} y={y} width={chartBarWidth} height={height} fill={color}
                      stroke={label === "Reassigned" && count > 0 ? "var(--line)" : "none"} strokeWidth="1" />;
                  });
                  const labelY = chartBaseline + 32;
                  return <g className="chart-member" key={member.id} role="button" tabIndex="0"
                    aria-label={`${member.name}: ${segments.map(([label, count]) => `${count} ${label.toLowerCase()}`).join(", ")}`}
                    onClick={() => go("memberStatus", { id: member.id })}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        go("memberStatus", { id: member.id });
                      }
                    }}>
                    <title>{member.name}: {total} tasks. View individual metrics.</title>
                    {bars}
                    <text x={center - 3} y={labelY} textAnchor="start" fontSize="10"
                      transform={`rotate(-45 ${center - 3} ${labelY})`}>{member.name.split(" ")[0]}</text>
                  </g>;
                })}
              </svg>
            </div>
            <p className="metrics-note">Counts reflect tasks currently assigned to each member.</p>
            {live && <p className="metrics-note">Transfer history is unavailable until the backend exposes reassignment data.</p>}
          </div>
          <div className="panel">
            <h2>Recent Reassignment Requests</h2>
            {live
              ? <p className="metrics-note">Reassignment requests are not connected to the backend yet.</p>
              : <div className="metrics-recent-list">{[...reqs].slice(0, 6).map((request) => (
                <div className="metrics-request" key={request.id}>
                  <b>{task(request.task)?.title ?? "Task"}</b>
                  <div>{person(request.from)?.name} to {person(request.to)?.name}</div>
                  <div>{request.reason}</div>
                  <small>{request.requestedAt} · {request.status}</small>
                </div>
              ))}{!reqs.length && <p className="empty">No requests yet.</p>}</div>}
          </div>
          <div className="panel">
            <h2>View Individual Metrics</h2>
            <div className="metrics-member-list">{PEOPLE.map((member) => {
              const status = getMemberStatus(member);
              return <button className="metrics-member-link" key={member.id} onClick={() => go("memberStatus", { id: member.id })}>
                <span className="avatar sm" aria-hidden="true">{ini(member.name)}</span><span>{member.name}<small>{member.role} · {status.completed.length} completed</small></span>
              </button>;
            })}</div>
          </div>
        </div>
      </>);
      break;
    }
    case "memberStatus": {
      const member = person(p.id);
      const status = getMemberStatus(member);
      const reassignment = getReassignmentCounts(member);
      const highestReassignment = Math.max(1, reassignment.requested, reassignment.approved, reassignment.received);
      const attended = live ? null : MEETINGS.filter((meeting) =>
        (attendanceByMeeting[meeting.id] ?? []).some((id) => sameMember(id, member.id)),
      ).length;
      const groups = [
        ["Completed", status.completed],
        ["Pending", status.pending],
        ["Overdue", status.overdue],
        ["Transferred", status.transferred],
      ];
      page = (<><Top title="Current Member Status" tag /><Ident q={member} />
        <div className="metrics-stat-grid">
          {groups.map(([label, items]) => <div className="metrics-stat" key={label}><strong>{items.length}</strong><span>{label}</span></div>)}
          <div className="metrics-stat"><strong>{attended === null ? "—" : `${attended}/${MEETINGS.length}`}</strong><span>Meetings Attended</span></div>
        </div>
        <div className="panel" style={{ marginBottom: 18 }}>
          <h3 style={{ marginTop: 0 }}>Reassignment Activity</h3>
          <div className="reassignment-chart">
            {[["Requests made", reassignment.requested], ["Approved transfers out", reassignment.approved], ["Transfers received", reassignment.received]]
              .map(([label, count]) => <div className="reassignment-bar-row" key={label}>
                <span>{label}</span><span className="reassignment-bar-track"><i style={{ width: `${count / highestReassignment * 100}%` }} /></span><b>{count}</b>
              </div>)}
          </div>
          {live && <p className="metrics-note">Reassignment history is not available from the current backend.</p>}
          {!live && <p className="metrics-note">Sample history is shown for this session only.</p>}
        </div>
        <div className="metrics-task-list">
          {groups.map(([label, items]) => <div className="panel" key={label}>
            <h3>{label} Tasks</h3>
            {items.length ? items.map((item) => <div className="due" key={item.id}>
              <button className="pill" onClick={() => go("task", { id: item.id })}>{item.title}</button><span>{item.due}</span>
            </div>) : <p className="metrics-note">No {label.toLowerCase()} tasks.</p>}
          </div>)}
        </div>
      </>);
      break;
    }
    case "attendance": {
      const meeting = MEETINGS.find((item) => sameMember(item.id, attendanceMeetingId)) ?? MEETINGS[0];
      const attendees = attendanceByMeeting[attendanceMeetingId] ?? [];
      page = (<><Top title="Meeting Attendance" tag />
        <div className="panel" style={{ maxWidth: 820, width: "100%", margin: "0 auto" }}>
          <label style={{ display: "grid", gap: 8, fontWeight: 700 }}>Meeting
            <select className="field" value={attendanceMeetingId} onChange={(event) => setAttendanceMeetingId(event.target.value)}>
              {MEETINGS.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.date}</option>)}
            </select>
          </label>
          {meeting && <><h3>{meeting.name}</h3><p className="metrics-note">Select the board members who attended this meeting.</p>
            <div className="attendance-list">{PEOPLE.map((member) => <label className="attendance-member" key={member.id}>
              <input type="checkbox" checked={attendees.some((id) => sameMember(id, member.id))}
                onChange={(event) => setAttendanceByMeeting((current) => {
                  const selected = current[attendanceMeetingId] ?? [];
                  const next = event.target.checked
                    ? [...selected, member.id]
                    : selected.filter((id) => !sameMember(id, member.id));
                  return { ...current, [attendanceMeetingId]: [...new Set(next)] };
                })} />
              <span>{member.name} <small>{member.role}</small></span>
            </label>)}</div>
            <div style={{ textAlign: "center", marginTop: 18 }}><button className="btn" onClick={saveMeetingAttendance}>Save Attendance</button></div>
          </>}
          <p className="metrics-note">{live
            ? "Meetings and attendance are sample data; changes are not persisted to the backend."
            : "Attendance changes stay in this session only."}</p>
        </div>
      </>);
      break;
    }
    case "editlist":
      page = <Grid title="Edit Profiles" tag onPick={(q) => go("edit", { id: q.id })} />;
      break;
    case "edit": {
    const q = person(p.id);
    const profileDraft = profileDrafts[q.id] ?? {
      previousRoles: (q.previousRoles ?? []).join("\n"),
      previousRoleSkills: (q.previousRoleSkills ?? []).join("\n"),
    };
    const savePreviousRoles = () => {
      if (live) {
        say("Previous roles are not connected to the backend yet; nothing was saved.");
        return;
      }
      const previousRoles = profileDraft.previousRoles.split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
      const previousRoleSkills = profileDraft.previousRoleSkills.split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
      setPeople((current) => current.map((member) => {
        if (!sameMember(member.id, q.id)) return member;
        const regularSkills = (member.skills ?? []).filter((skill) => !(member.previousRoleSkills ?? []).includes(skill));
        return { ...member, previousRoles, previousRoleSkills, skills: [...new Set([...regularSkills, ...previousRoleSkills])] };
      }));
      setProfileDrafts((current) => ({ ...current, [q.id]: { previousRoles: previousRoles.join("\n"), previousRoleSkills: previousRoleSkills.join("\n") } }));
      say("Previous roles and skills saved in sample data for this session only.");
    };
      page = (<><Top title="Edit Profile" tag /><div className="id"><Avatar p={q} cls="lg" tabIndex={-1} /><div style={{ flex: 1 }}><input className="field" defaultValue={q.name} aria-label="Name" style={{ maxWidth: 500, fontSize: 26 }} /><input className="field" defaultValue={q.role} aria-label="Position" style={{ maxWidth: 500, marginTop: 8 }} /></div></div>
        <div className="two"><div className="panel"><h3>Edit Tasks</h3><ul>{TASKS.filter((t) => owns(t, q.id)).map((t) => <li key={t.id}>{t.title} ({t.status})</li>)}</ul></div>
          <div className="panel"><h3>Edit Skills</h3><ul>{q.skills.map((s) => <li key={s}><input className="field" defaultValue={s} style={{ padding: "4px 12px", width: "80%" }} /></li>)}</ul></div></div>
      <div className="panel" style={{ marginTop: 18 }}><h3>Previous Roles &amp; Skills</h3>
        <label>Previous roles (one per line)<textarea className="field" rows={3} value={profileDraft.previousRoles} disabled={live}
          onChange={(event) => setProfileDrafts((current) => ({ ...current, [q.id]: { ...profileDraft, previousRoles: event.target.value } }))} /></label>
        <label style={{ display: "block", marginTop: 12 }}>Skills gained from those roles (one per line)<textarea className="field" rows={3} value={profileDraft.previousRoleSkills} disabled={live}
          onChange={(event) => setProfileDrafts((current) => ({ ...current, [q.id]: { ...profileDraft, previousRoleSkills: event.target.value } }))} /></label>
        <p className="metrics-note">{live ? "Previous roles are read-only until backend support is available." : "These skills are added to the member profile for this session only."}</p>
      </div>
      <div style={{ textAlign: "center", marginTop: 18 }}><button className="btn" disabled={live} onClick={savePreviousRoles}>Save Previous Roles &amp; Skills</button></div></>);
      break;
    }
    case "evals":
      page = <Grid title="Member Performance" tag description="Select a member to review their performance evaluation." onPick={(q) => go("eval", { id: q.id })} />;
      break;
    case "eval": {
      const q = person(p.id), seed = seedOf(q.id) * 7;
      const M = [["On-time task completion", 70 + (seed % 28)], ["Meeting attendance", 66 + ((seed * 3) % 32)], ["Task follow-through (not reassigned)", 74 + ((seed * 5) % 24)], ["Deadline buffer (avg. early completion)", 55 + ((seed * 2) % 40)]];
      const overall = Math.round(M.reduce((a, b) => a + b[1], 0) / M.length);
      page = (<><Top title={`${q.name}'s Evaluation`} tag /><Ident q={q} />
        <div className="score"><div className="panel" style={{ textAlign: "center" }}><h3>Overall score</h3><div className="big">{overall}%</div><p>Based on placeholder metrics — backend supplies real data.</p></div>
          <div className="panel">{M.map(([k, v]) => <div key={k} style={{ marginBottom: 12 }}><div className="lbl">{k}: {v}%</div><div className="meter"><i style={{ width: `${v}%` }} /></div></div>)}</div></div>
        <div className="panel" style={{ marginTop: 18 }}><h3>Admin comments</h3><textarea className="field" placeholder="Write feedback for this member…" /><div style={{ textAlign: "center", marginTop: 10 }}><button className="btn" onClick={() => say("Evaluation saved (placeholder)")}>Save evaluation</button></div></div></>);
      break;
    }
    case "taskmetrics":
      page = <Grid title="Task Completion" tag description="Select a member to review completed tasks, or view reassignment history." onPick={(q) => go("tm", { id: q.id })} extra={<div style={{ textAlign: "center", marginTop: 20 }}><button className="btn alt" onClick={() => go("reassigned")}>View Reassigned Tasks</button></div>} />;
      break;
    case "tm": {
      const q = person(p.id), done = TASKS.filter((t) => t.status === "Completed" && (!live || owns(t, q.id)));
      page = (<><Top title={`${q.name}'s Completed Tasks`} tag /><Ident q={q} /><h3 style={{ textAlign: "center", fontSize: 26, margin: "0 0 10px" }}>Tasks Completed: {done.length}</h3>
        {done.map((t) => <div className="due" key={t.id}><span style={{ width: 110, fontSize: 18 }}>{t.finished}:</span><button className="pill" onClick={() => go("task", { id: t.id })}>{t.title}</button></div>)}</>);
      break;
    }
    case "reassigned":
    case "review": {
      const approvedOnly = p.n === "reassigned";
      const visible = approvedOnly ? reqs.filter(r => r.status === "approved") : reqs;
      const pending = visible.filter(r => r.status === "pending");
      const history = visible.filter(r => r.status !== "pending");
      const card = (r) => <div className="req" key={r.id}>
        <div className="panel"><strong>{task(r.task_id)?.title || `Task ${r.task_id}`}</strong>
          <p>Requested by {person(r.requester_code)?.name || r.requester_code}</p>
          <p>Proposed assignee: {person(r.proposed_assignee_code)?.name || r.proposed_assignee_code}</p>
          <p>{r.reason || "No reason provided."}</p>
          <small>{new Date(r.created_at).toLocaleString()} ? {r.status}</small>
          {r.review_note && <p>Review: {r.review_note}</p>}
        </div>
        {admin && r.status === "pending" && <>
          <button className="btn" disabled={requestBusy || !!dataError} onClick={() => decideRequest(r, "approved")}>Approve</button>
          <button className="btn alt" disabled={requestBusy || !!dataError} onClick={() => decideRequest(r, "rejected")}>Deny</button>
        </>}
      </div>;
      page = <><Top title={approvedOnly ? "Approved Reassignments" : admin ? "Reassignment Requests" : "Your Reassignment Requests"} tag={admin} />
        <button className="btn alt" onClick={() => refresh().catch(() => {})}>Refresh</button>
        {requestError && <p role="alert">{requestError}</p>}
        {!approvedOnly && <><h2>Pending ({pending.length})</h2>{pending.map(card)}
          {!loading && !dataError && !pending.length && <p className="empty">No pending requests.</p>}</>}
        <h2>{approvedOnly ? "Approved" : "History"}</h2>{history.map(card)}
      </>;
      break;
    }
    case "meetmetrics":
      page = <Grid title="Meeting Attendance" tag description="Select a member to see the meetings they attended." onPick={(q) => go("mm", { id: q.id })} />;
      break;
    case "mm": {
      const q = person(p.id);
      page = (<><Top title={`${q.name}'s Meeting Attendance`} tag /><Ident q={q} /><h3 style={{ textAlign: "center", fontSize: 26, margin: "0 0 10px" }}>Meetings Attended: {MEETINGS.length}</h3>
        {MEETINGS.map((m) => <div className="due" key={m.id}><span style={{ width: 110, fontSize: 18 }}>{m.date}:</span><button className="pill" style={{ textAlign: "center" }} onClick={() => go("meeting", { id: m.id })}>Review</button></div>)}</>);
      break;
    }
    default: page = null;
  }

  // The "Profiles" grid for admins opens a profile first, where clicking the name offers dashboard view
  return (
    <div className="app"><style>{CSS}</style><header style={{ display: "flex", justifyContent: "flex-end", gap: 16 }}>
        <button className="link" onClick={() => go("review")}>Requests ({reqs.filter(r => r.status === "pending").length})</button>
        <button className="link" onClick={signOut}>Sign out</button>
      </header>
      {dataError && <div role="alert">Could not refresh Supabase data: {dataError} <button onClick={() => refresh().catch(() => {})}>Retry</button></div>}
      {loading && <p role="status">Loading tasks and requests?</p>}
      <main className="page-content">{page}</main>{p.n === "dash" && <Nav />}
      {modal?.view && (<div className="modal"><div className="box">View {modal.view.name}’s page?<div className="acts"><button className="btn alt" onClick={() => setModal(null)}>Cancel</button>
        <button className="btn" onClick={() => { setViewAs(modal.view.id); setModal(null); setStack([{ n: "dash" }]); }}>Confirm</button></div></div></div>)}
      {modal?.reassign && (<div className="modal"><div className="box">Request to reassign “{modal.reassign[0].title}” to {modal.reassign[1].name}?<br />
        {modal.reassign[2] && <small style={{ display: "block", margin: "6px 0" }}><b>{modal.reassign[2].fit === "strong" ? "Strong fit" : "Possible fit"}:</b> {modal.reassign[2].reason}<br />
          Skills: {modal.reassign[2].matched_skills.join(", ")} · {modal.reassign[2].due_this_week} due this week, {modal.reassign[2].open} open</small>}
        <small>Your request goes to the president, VP, or an admin for approval.</small>
        <label style={{ display: "block", marginTop: 12 }}>Reason (optional)
          <textarea className="field" maxLength={10000} value={requestReason} onChange={e => setRequestReason(e.target.value)} disabled={requestBusy} />
        </label>
        {requestError && <p role="alert">{requestError}</p>}
        {!profile.member_code && <p role="alert">Your account must be linked to the member roster before requesting a reassignment.</p>}
        <div className="acts"><button className="btn alt" disabled={requestBusy} onClick={() => setModal(null)}>Cancel</button><button className="btn" disabled={requestBusy || !profile.member_code || !live} onClick={sendRequest}>{requestBusy ? "Saving?" : "Send request"}</button></div></div></div>)}
      {recorder && <Recorder kind={recorder} onClose={() => setRecorder(null)} />}
      {toast && <div className="toast" role="status">{toast}</div>}
      <div role="status" style={{ position: "fixed", top: 8, right: 12, fontSize: 12, padding: "4px 10px", borderRadius: 999, background: live ? "#7fb08a" : "#e8a36b", color: "#fff", fontWeight: 700 }}>{source}</div>
    </div>
  );
}
