import { useState, Fragment } from "react";

/* ---------- Placeholder data (replace with backend responses) ---------- */
const PEOPLE = [
  { id: 1, name: "Maya Patel", role: "President", skills: ["Leadership", "Public speaking", "Budgeting"] },
  { id: 2, name: "Jordan Lee", role: "Vice President", skills: ["Planning", "Outreach", "Docs"] },
  { id: 3, name: "Sam Rivera", role: "Treasurer", skills: ["Budgeting", "Spreadsheets", "Sponsorship"] },
  { id: 4, name: "Priya Shah", role: "Secretary", skills: ["Note-taking", "Scheduling", "Docs"] },
  { id: 5, name: "Alex Kim", role: "Event Coordinator", skills: ["Logistics", "Planning", "Vendors"] },
  { id: 6, name: "Dana Cruz", role: "Event Coordinator", skills: ["Design", "Logistics", "Outreach"] },
  { id: 7, name: "Riley Chen", role: "PR Chair", skills: ["Design", "Social media", "Writing"] },
  { id: 8, name: "Taylor Brooks", role: "PR Chair", skills: ["Photography", "Writing", "Outreach"] },
];
// day = start column (0 = Mon), len = days wide, dep = id of task it depends on
const TASKS = [
  { id: 1, title: "Draft GBM 1 agenda", assigned: "11/02/2026", start: "11/09/2026", due: "11/10/2026", finished: "11/10/2026", assignee: 2, status: "Completed", dep: null, day: 0, len: 1.2, notes: "" },
  { id: 2, title: "Book GBM 1 room", assigned: "11/02/2026", start: "11/10/2026", due: "11/11/2026", finished: "", assignee: 5, status: "In-Progress", dep: 1, day: 1, len: 1.2, notes: "Waiting on facilities reply." },
  { id: 3, title: "Allocate budget for GBM 1", assigned: "11/03/2026", start: "11/11/2026", due: "11/13/2026", finished: "", assignee: 3, status: "Upcoming", dep: 2, day: 2, len: 2, notes: "" },
  { id: 4, title: "Design GBM 1 flyer", assigned: "11/03/2026", start: "11/10/2026", due: "11/12/2026", finished: "", assignee: 7, status: "In-Progress", dep: null, day: 1, len: 2, notes: "" },
  { id: 5, title: "Post flyer on socials", assigned: "11/04/2026", start: "11/12/2026", due: "11/14/2026", finished: "", assignee: 8, status: "Upcoming", dep: 4, day: 3, len: 1.6, notes: "" },
  { id: 6, title: "Order snacks", assigned: "11/04/2026", start: "11/13/2026", due: "11/15/2026", finished: "", assignee: 6, status: "Upcoming", dep: 3, day: 4, len: 1.8, notes: "" },
];
const MEETINGS = [
  { id: 1, date: "11/13/26", name: "Fall 2026 E-Board Meeting", tasks: [[ "Allocate budget for GBM 1", 3], ["Design GBM 1 flyer", 7]] },
  { id: 2, date: "11/10/26", name: "Finance Logistics Meeting", tasks: [["Book GBM 1 room", 5]] },
  { id: 3, date: "11/06/26", name: "P/VP Transition Meeting", tasks: [["Draft GBM 1 agenda", 2]] },
];
const REQUESTS = [{ id: 1, task: 3, from: 3, to: 1 }, { id: 2, task: 5, from: 8, to: 7 }, { id: 3, task: 6, from: 6, to: 5 }];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const COLORS = { Upcoming: "#e8a36b", "In-Progress": "#d9695a", Completed: "#7fb08a" };
const person = (id) => PEOPLE.find((p) => p.id === id);
const task = (id) => TASKS.find((t) => t.id === id);

/* ---------- Styles (palette pulled from the logo) ---------- */
const CSS = `
:root{--ink:#4a1109;--maroon:#5a0d05;--rust:#b5472a;--orange:#e07a4a;--salmon:#f6b3a0;--peach:#fbe3d3;--sun:#ffd98a;--paper:#fffaf5;--panel:#f8e6da;--line:#ecc9b6}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:"Nunito","Segoe UI",system-ui,sans-serif}
.app{max-width:1100px;margin:0 auto;min-height:100vh;display:flex;flex-direction:column;padding:20px 28px 0;position:relative}
.top{display:flex;align-items:center;gap:16px;min-height:56px;margin-bottom:12px}
.top h1{flex:1;text-align:center;font-size:26px;margin:0;font-weight:800;color:var(--maroon)}
.top .sp{width:44px}
.back{border:0;background:var(--peach);color:var(--maroon);width:44px;height:44px;border-radius:50%;font-size:22px;cursor:pointer}
.adm{color:#d83a3a;font-weight:800;font-size:20px;min-width:96px;text-align:right}
button{font-family:inherit}
.btn{border:0;background:var(--rust);color:#fff;font-weight:800;font-size:16px;padding:12px 26px;border-radius:999px;cursor:pointer}
.btn:hover{background:var(--maroon)}.btn.alt{background:var(--peach);color:var(--maroon)}.btn.alt:hover{background:var(--salmon)}
.btn.out{background:#fff;color:var(--maroon);border:2px solid var(--maroon)}
.link{background:none;border:0;color:var(--maroon);text-decoration:underline;font-size:18px;cursor:pointer;margin-top:10px}
button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:3px solid var(--sun);outline-offset:2px}
.center{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;gap:14px;padding-bottom:60px}
.center h2{font-size:34px;margin:0;color:var(--maroon);border-bottom:3px solid var(--maroon);padding:0 60px 10px;width:min(700px,100%)}
.logo{width:150px;height:150px;object-fit:contain}
.form{display:grid;grid-template-columns:auto 280px;gap:14px 14px;align-items:center;text-align:right;font-size:20px;font-weight:700}
.field{border:0;background:var(--panel);border-radius:999px;padding:12px 18px;font-size:16px;color:var(--ink);font-family:inherit;width:100%}
textarea.field{border-radius:18px;min-height:110px;resize:vertical}
.pill{background:var(--panel);border-radius:999px;padding:14px 24px;font-size:18px;font-weight:600;border:0;color:var(--ink);text-align:left;font-family:inherit}
button.pill{cursor:pointer}button.pill:hover{background:var(--salmon)}
.panel{background:var(--panel);border-radius:24px;padding:20px 26px}
.panel h3{margin:0 0 10px;text-align:center;font-size:24px;color:var(--maroon)}
.panel ul{margin:0;padding-left:22px;line-height:1.9;font-size:18px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:24px}
.avatar{width:56px;height:56px;border-radius:50%;background:var(--salmon);border:3px solid var(--maroon);display:grid;place-items:center;font-weight:800;color:var(--maroon);flex:none;cursor:pointer;padding:0;font-size:17px}
.avatar.sm{width:44px;height:44px;font-size:14px}
.avatar.lg{width:110px;height:110px;font-size:36px;cursor:default;border-width:4px}
.id{display:flex;gap:26px;align-items:center;margin-bottom:12px}
.id h2{margin:0;font-size:32px;border-bottom:3px solid var(--maroon);padding-bottom:8px;flex:1;max-width:640px}
.id p{margin:6px 0 0;font-size:20px}
.grid2{display:grid;grid-template-columns:1fr 3px 1fr;gap:20px 28px;margin-top:20px}
.divider{border-left:3px dashed var(--maroon);grid-row:1/5;grid-column:2}
.row{display:flex;align-items:center;gap:14px}.row .pill{flex:1;text-align:center}
.home{display:grid;grid-template-columns:1fr 330px;gap:28px;flex:1}
.home h3{text-align:center;font-size:26px;margin:0 0 10px}
.nav{display:grid;grid-template-columns:1fr 1fr 1fr;gap:28px;background:var(--panel);margin:18px -28px 0;padding:18px 28px;position:sticky;bottom:0}
.nav button{border:0;background:#fff;border-radius:999px;padding:12px;font-size:24px;font-weight:700;color:var(--maroon);cursor:pointer}
.nav button:hover{background:var(--sun)}
.bell{position:relative;background:none;border:0;font-size:30px;cursor:pointer}
.bell b{position:absolute;right:-4px;top:-4px;background:var(--rust);color:#fff;border-radius:50%;width:20px;height:20px;font-size:12px;display:grid;place-items:center}
.due{display:flex;align-items:center;gap:10px;margin-bottom:12px}
.due .pill{flex:1;padding:12px 20px}
.dot{width:26px;height:26px;border-radius:50%;flex:none;border:0}
.gantt{background:var(--panel);border-radius:20px;overflow:hidden;font-size:13px}
.gh,.gr{display:grid;grid-template-columns:150px 84px 84px 84px 1fr;align-items:center}
.gh{background:var(--peach);font-weight:800;padding:8px 10px;gap:4px}
.gr{padding:4px 10px;gap:4px;height:40px;border-top:1px solid var(--line);cursor:pointer}
.gr:hover{background:#fff6ee}
.gr span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.days{display:grid;grid-template-columns:repeat(7,1fr);text-align:center;font-weight:700}
.lane{position:relative;height:100%;background:repeating-linear-gradient(90deg,transparent 0 calc(100%/7 - 1px),var(--line) calc(100%/7 - 1px) calc(100%/7))}
.bar{position:absolute;top:9px;height:22px;border-radius:6px;box-shadow:inset 0 -3px 0 rgba(0,0,0,.12)}
.tog{display:flex;align-items:center;gap:8px;justify-content:flex-end;font-size:14px;margin-bottom:6px;cursor:pointer}
.sw{width:44px;height:24px;border-radius:99px;background:var(--line);position:relative}
.sw i{position:absolute;top:3px;left:3px;width:18px;height:18px;border-radius:50%;background:var(--maroon);transition:left .15s}
.sw.on{background:var(--salmon)}.sw.on i{left:23px}
.legend{display:flex;gap:16px;margin-top:8px;font-size:14px;justify-content:center}
.legend i{display:inline-block;width:14px;height:14px;border-radius:4px;margin-right:6px;vertical-align:-2px}
.sec{font-size:26px;margin:18px 0 8px}
.sum{display:grid;grid-template-columns:1fr 240px;gap:8px 14px;align-items:center;max-width:960px;margin:0 auto;width:100%}
.sum .pill{display:flex;justify-content:space-between;align-items:center;width:100%;cursor:pointer}
.chev{background:none;border:0;font-size:22px;cursor:pointer;color:var(--maroon);transition:transform .15s}
.chev.open{transform:rotate(180deg)}
.det{grid-column:1/-1;background:#fff;border-radius:18px;padding:10px 20px;margin:-2px 0 6px;font-size:16px}
.modal{position:fixed;inset:0;background:rgba(74,17,9,.35);display:grid;place-items:center;z-index:9}
.box{background:#fff;border:3px solid var(--maroon);border-radius:26px;padding:26px 34px;text-align:center;max-width:480px;font-size:20px;line-height:1.5}
.box h4{margin:0 0 8px;font-size:22px;text-decoration:underline}
.box .acts{display:flex;gap:14px;justify-content:center;margin-top:14px}
.toast{position:fixed;bottom:96px;left:50%;transform:translateX(-50%);background:var(--maroon);color:#fff;padding:12px 24px;border-radius:999px;z-index:10;font-weight:700}
.hub{display:grid;grid-template-columns:1fr 1fr;gap:18px;max-width:880px;margin:30px auto}
.hub button{background:var(--panel);border:0;padding:30px;font-size:24px;font-weight:700;color:var(--maroon);border-radius:20px;cursor:pointer}
.hub button:hover{background:var(--salmon)}.hub button:last-child:nth-child(odd){grid-column:1/-1;justify-self:center;width:50%}
.lbl{font-weight:800;font-size:18px}
.meter{height:16px;background:#fff;border-radius:99px;overflow:hidden}.meter i{display:block;height:100%;background:linear-gradient(90deg,var(--orange),var(--sun))}
.score{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.big{font-size:44px;font-weight:800;color:var(--rust)}
.cols{display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px}
.cols .panel{min-height:320px}
.cols .panel p{white-space:pre-wrap;font-size:15px;line-height:1.7}
.req{display:flex;align-items:center;gap:18px;margin-bottom:16px}
.req .panel{flex:1;text-align:center;font-size:19px;line-height:1.5;border-radius:30px}
.rb{width:54px;height:54px;border-radius:50%;border:0;color:#fff;font-size:26px;cursor:pointer}
.side{display:flex;flex-direction:column;gap:12px}.side .pill{text-align:center;background:var(--maroon);color:#fff;cursor:pointer}.side .pill.on{background:var(--rust)}
@media(max-width:800px){.home,.two,.cols,.score,.hub{grid-template-columns:1fr}.gh,.gr{grid-template-columns:110px 0 0 0 1fr}.gh span:nth-child(2),.gh span:nth-child(3),.gh span:nth-child(4),.gr span:nth-child(2),.gr span:nth-child(3),.gr span:nth-child(4){display:none}.grid2{grid-template-columns:1fr}.divider{display:none}.sum{grid-template-columns:1fr}.hub button:last-child:nth-child(odd){width:100%}}
`;

const ini = (n) => n.split(" ").map((w) => w[0]).join("");
const Avatar = ({ p, cls = "", ...r }) => <button className={`avatar ${cls}`} title={p.name} aria-label={p.name} {...r}>{ini(p.name)}</button>;

/* ---------- Gantt ---------- */
function Gantt({ tasks, onOpen }) {
  const [deps, setDeps] = useState(false);
  const H = 40, W = 700, cw = W / 7;
  const idx = Object.fromEntries(tasks.map((t, i) => [t.id, i]));
  return (
    <div>
      <label className="tog" onClick={() => setDeps(!deps)}>Toggle dependency view <span className={`sw ${deps ? "on" : ""}`}><i /></span></label>
      <div className="gantt">
        <div className="gh"><span>Task title</span><span>Start date</span><span>Due date</span><span>Date finished</span>
          <div className="days">{DAYS.map((d) => <span key={d}>{d}</span>)}</div></div>
        <div style={{ position: "relative" }}>
          {tasks.map((t) => (
            <div className="gr" key={t.id} onClick={() => onOpen(t.id)}>
              <span>{t.title}</span><span>{t.start.slice(0, 5)}</span><span>{t.due.slice(0, 5)}</span><span>{t.finished ? t.finished.slice(0, 5) : "—"}</span>
              <div className="lane"><div className="bar" style={{ left: `${(t.day / 7) * 100}%`, width: `${(t.len / 7) * 100}%`, background: COLORS[t.status] }} /></div>
            </div>
          ))}
          {deps && (
            <svg viewBox={`0 0 ${W} ${tasks.length * H}`} preserveAspectRatio="none" style={{ position: "absolute", top: 0, right: 10, width: "calc(100% - 436px)", height: tasks.length * H, pointerEvents: "none" }}>
              {tasks.filter((t) => t.dep && idx[t.dep] !== undefined).map((t) => {
                const a = task(t.dep), x1 = (a.day + a.len) * cw, y1 = idx[a.id] * H + H / 2, x2 = (t.day + 0.1) * cw, y2 = idx[t.id] * H + 9;
                return <path key={t.id} d={`M${x1} ${y1} H${x1 + 8} V${y2 - 4} H${x2} V${y2}`} fill="none" stroke="#4a1109" strokeWidth="1.6" vectorEffect="non-scaling-stroke" />;
              })}
            </svg>
          )}
        </div>
      </div>
      <div className="legend">{Object.entries(COLORS).map(([k, c]) => <span key={k}><i style={{ background: c }} />{k}</span>)}</div>
    </div>
  );
}

/* ---------- App ---------- */
export default function App() {
  const [stack, setStack] = useState([{ n: "landing" }]);
  const [admin, setAdmin] = useState(false);
  const [viewAs, setViewAs] = useState(null);
  const [modal, setModal] = useState(null);
  const [toast, setToast] = useState("");
  const [reqs, setReqs] = useState(REQUESTS);
  const [open, setOpen] = useState({});
  const [notes, setNotes] = useState({});
  const p = stack[stack.length - 1];
  const go = (n, x = {}) => setStack((s) => [...s, { n, ...x }]);
  const back = () => setStack((s) => (s.length > 1 ? s.slice(0, -1) : s));
  const home = () => { setStack([{ n: "landing" }]); setViewAs(null); setAdmin(false); };
  const say = (m) => { setToast(m); setTimeout(() => setToast(""), 2400); };
  const isAdminView = admin && !viewAs;
  const me = viewAs ? person(viewAs) : person(isAdminView ? 1 : 2);

  const Top = ({ title, tag, noBack }) => (
    <div className="top">
      {noBack ? <span className="sp" /> : <button className="back" onClick={back} aria-label="Back">←</button>}
      <h1>{title}</h1>{tag ? <span className="adm">(ADMIN)</span> : <span className="sp" />}
    </div>
  );
  const Ident = ({ q, sub }) => (
    <div className="id"><Avatar p={q} cls="lg" tabIndex={-1} /><div><h2>{q.name}</h2><p>{q.role}</p></div></div>
  );
  const Grid = ({ title, tag, onPick, extra }) => (
    <>
      <Top title={title} tag={tag} />
      <div className="grid2"><div className="divider" />
        {PEOPLE.map((q, i) => (
          <div className="row" key={q.id} style={{ gridColumn: i < 4 ? 1 : 3, gridRow: (i % 4) + 1 }}>
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
  switch (p.n) {
    case "landing":
      page = (<div className="center"><img className="logo" src="/wics-logo.png" alt="WiCS logo" onError={(e) => (e.target.style.display = "none")} />
        <h2>Ask Winnie!</h2><button className="btn" style={{ width: 260, fontSize: 24 }} onClick={() => go("login")}>Login</button>
        <button className="link" onClick={() => go("register")}>Create an account</button></div>);
      break;
    case "login":
      page = (<div className="center"><h2>Login:</h2>
        <div className="form"><label htmlFor="u">Username:</label><input id="u" className="field" onChange={(e) => (window.__u = e.target.value)} />
          <label htmlFor="pw">Password:</label><input id="pw" type="password" className="field" /></div>
        <button className="btn" onClick={() => { const a = /admin/i.test(window.__u || ""); setAdmin(a); setStack([{ n: "dash" }]); }}>Submit</button>
        <button className="btn out" onClick={() => go("reset")}>Reset your password</button>
        <button className="link" onClick={home}>Back to Home</button></div>);
      break;
    case "reset":
      page = (<div className="center"><h2>Reset Password:</h2>
        <div className="form"><label>Email:</label><input type="email" className="field" /><label>Set Password:</label><input type="password" className="field" /><label>Confirm Password:</label><input type="password" className="field" /></div>
        <button className="btn" onClick={() => say("Reset email sent (placeholder — backend will send it)")}>Submit</button>
        <button className="link" onClick={home}>Back to Home</button></div>);
      break;
    case "register":
      page = (<div className="center"><h2>Register:</h2>
        <div className="form"><label>Name:</label><input className="field" /><label>Email:</label><input type="email" className="field" /><label>Username:</label><input className="field" /><label>Password:</label><input type="password" className="field" /><label>Confirm Password:</label><input type="password" className="field" /></div>
        <button className="btn" onClick={() => go("registered")}>Submit</button><button className="link" onClick={home}>Back to Home</button></div>);
      break;
    case "registered":
      page = (<div className="center"><h2 style={{ lineHeight: 1.3 }}>Your account has been successfully registered!</h2><p style={{ fontSize: 20, margin: 0 }}>You can now login with your registered credentials.</p><button className="link" onClick={home}>Back to Home</button></div>);
      break;
    case "dash": {
      const mine = viewAs ? TASKS.filter((t) => t.assignee === viewAs) : isAdminView ? TASKS : TASKS.filter((t) => t.assignee === 2 || t.dep);
      const soon = TASKS.filter((t) => t.status !== "Completed").slice(0, isAdminView ? 3 : 4);
      page = (<>
        <div className="top"><h1 style={{ textAlign: "left", fontSize: 36, fontWeight: 600 }}>Hey {me.name.split(" ")[0]}!</h1>
          {viewAs ? <button className="btn alt" onClick={() => { setViewAs(null); setStack([{ n: "dash" }, { n: "admin" }]); }}>BACK TO ADMIN</button>
            : isAdminView ? <button className="btn alt" onClick={() => go("admin")}>ADMIN SETTINGS</button>
            : <button className="bell" aria-label="Notifications" onClick={() => setModal("notif")}>🔔<b>1</b></button>}
          <Avatar p={me} onClick={() => go("profile", { id: me.id })} /></div>
        <div className="home"><div><h3>Your Gantt Chart:</h3><Gantt tasks={mine} onOpen={(id) => go("task", { id })} /></div>
          <div><h3>Due Soon:</h3>{soon.map((t) => (<div className="due" key={t.id}>
            {isAdminView && <Avatar p={person(t.assignee)} cls="sm" onClick={() => go("profile", { id: t.assignee })} />}
            <button className="pill" onClick={() => go("task", { id: t.id })}>{t.title}</button>
            {!isAdminView && <span className="dot" style={{ background: COLORS[t.status] }} title={t.status} />}</div>))}</div></div>
        <Nav /></>);
      break;
    }
    case "meetings":
      page = (<><Top title="Meetings" /><div style={{ textAlign: "right", marginTop: -50, marginBottom: 20, fontSize: 20, pointerEvents: "none" }}>11/14/2026</div>
        <div className="two" style={{ gridTemplateColumns: "180px 1fr", gap: 24 }}>
          <div className="side panel">{["Internal", "Committee", "External"].map((k) => <button key={k} className="pill" onClick={() => say(`${k} recording started (placeholder)`)}>{k}</button>)}</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
            {["Internal", "Committee", "External"].map((k) => <button key={k} className="pill" style={{ padding: 28 }} onClick={() => say(`New ${k.toLowerCase()} recording — backend will store notes & transcript`)}>🎙&nbsp;&nbsp;Create a new recording</button>)}
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
            {m.tasks.map(([t, a]) => <div className="due" key={t}><span>➜</span><button className="pill" style={{ flex: 1, textAlign: "center" }} onClick={() => go("task", { id: TASKS.find((x) => x.title === t)?.id || 1 })}>{t}<br /><small>Assignee: {person(a).name}</small></button></div>)}</div></div></>);
      break;
    }
    case "profiles":
      page = <Grid title="Profiles" onPick={(q) => go("profile", { id: q.id })} />;
      break;
    case "profile": {
      const q = person(p.id), ts = TASKS.filter((t) => t.assignee === q.id);
      page = (<><Top title="Profile" tag={isAdminView} />
        <div className="id"><Avatar p={q} cls="lg" tabIndex={-1} /><div><h2 style={isAdminView ? { cursor: "pointer" } : {}} onClick={() => isAdminView && setModal({ view: q })}>{q.name}</h2><p>{q.role}</p></div></div>
        <div className="two"><div className="panel"><h3>Tasks</h3><ul>{ts.map((t) => <li key={t.id}><a href="#t" onClick={(e) => { e.preventDefault(); go("task", { id: t.id }); }}>{t.title}</a> ({t.status})</li>)}{!ts.length && <li>No tasks yet</li>}</ul></div>
          <div className="panel"><h3>Skills</h3><ul>{q.skills.map((s) => <li key={s}>{s}</li>)}</ul></div></div></>);
      break;
    }
    case "task": {
      const t = task(p.id), dep = t.dep ? task(t.dep) : null;
      const rows = [["Date assigned", t.assigned], ["Start date", t.start], ["Due date", t.due], ["Assignee", person(t.assignee).name], ["Status", t.status], ["Dependency", dep ? `Depends on “${dep.title}” (${person(dep.assignee).name})` : "None"]];
      page = (<><Top title={t.title} /><div className="two" style={{ maxWidth: 960, margin: "10px auto" }}>
        <div className="panel"><div className="form" style={{ textAlign: "left", fontSize: 18, gridTemplateColumns: "150px 1fr" }}>
          {rows.map(([k, v]) => [<span className="lbl" key={k}>{k}:</span>, k === "Status" ? <select key="s" className="field" defaultValue={v}>{Object.keys(COLORS).map((s) => <option key={s}>{s}</option>)}</select> : <span key={k + 1}>{v}</span>])}</div></div>
        <div className="panel"><h3>Notes</h3><textarea className="field" style={{ minHeight: 200 }} placeholder="Add notes for yourself or an admin…" value={notes[t.id] ?? t.notes} onChange={(e) => setNotes({ ...notes, [t.id]: e.target.value })} />
          <div style={{ textAlign: "center", marginTop: 12 }}><button className="btn" onClick={() => say("Notes saved (placeholder)")}>Save notes</button></div></div></div></>);
      break;
    }
    case "tasks": {
      const G = (title, st, avs) => (<>
        <h2 className="sec" style={{ gridColumn: 1 }}>{title}</h2>{avs ? <h2 className="sec" style={{ fontSize: 24 }}>Assign Task:</h2> : <span />}
        {TASKS.filter((t) => t.status === st).map((t) => (<Fragment key={t.id}>
          <div className="pill" onClick={() => go("task", { id: t.id })}><span>{t.title} - {t.due}</span>
            <button className={`chev ${open[t.id] ? "open" : ""}`} aria-label="Expand" onClick={(e) => { e.stopPropagation(); setOpen({ ...open, [t.id]: !open[t.id] }); }}>⌄</button></div>
          <div className="row" style={{ gap: 8 }}>{avs && PEOPLE.filter((q) => q.id !== t.assignee && q.skills.some((s) => ["Budgeting", "Design", "Logistics", "Outreach", "Planning", "Docs"].includes(s))).slice(0, 3).map((q) => <Avatar key={q.id} p={q} cls="sm" onClick={() => setModal({ reassign: [t, q] })} />)}</div>
          {open[t.id] && <div className="det">Assignee: {person(t.assignee).name} · Status: {t.status} · Assigned {t.assigned}</div>}</Fragment>))}</>);
      page = (<><Top title="Tasks Summary" /><div className="sum">{G("Due soon:", "Upcoming", 1)}{G("In progress:", "In-Progress", 1)}{G("Completed:", "Completed", 0)}</div></>);
      break;
    }
    case "admin":
      page = (<><Top title="Admin Settings" tag noBack /><div className="hub">
        <button onClick={() => go("editlist")}>Edit Profiles</button><button onClick={() => go("evals")}>Performance Evaluations</button>
        <button onClick={() => go("taskmetrics")}>Task Metrics</button><button onClick={() => go("review")}>Assign Tasks</button>
        <button onClick={() => go("meetmetrics")}>Meeting Metrics</button></div>
        <div style={{ textAlign: "center" }}><button className="btn alt" onClick={() => setStack([{ n: "dash" }])}>Back to dashboard</button></div></>);
      break;
    case "editlist":
      page = <Grid title="Edit Profiles" tag onPick={(q) => go("edit", { id: q.id })} />;
      break;
    case "edit": {
      const q = person(p.id);
      page = (<><Top title="Edit Profile" tag /><div className="id"><Avatar p={q} cls="lg" tabIndex={-1} /><div style={{ flex: 1 }}><input className="field" defaultValue={q.name} aria-label="Name" style={{ maxWidth: 500, fontSize: 26 }} /><input className="field" defaultValue={q.role} aria-label="Position" style={{ maxWidth: 500, marginTop: 8 }} /></div></div>
        <div className="two"><div className="panel"><h3>Edit Tasks</h3><ul>{TASKS.filter((t) => t.assignee === q.id).map((t) => <li key={t.id}>{t.title} ({t.status})</li>)}</ul></div>
          <div className="panel"><h3>Edit Skills</h3><ul>{q.skills.map((s) => <li key={s}><input className="field" defaultValue={s} style={{ padding: "4px 12px", width: "80%" }} /></li>)}</ul></div></div>
        <div style={{ textAlign: "center", marginTop: 18 }}><button className="btn" onClick={() => say("Profile saved (placeholder)")}>Save changes</button></div></>);
      break;
    }
    case "evals":
      page = <Grid title="Performance Evaluations" tag onPick={(q) => go("eval", { id: q.id })} />;
      break;
    case "eval": {
      const q = person(p.id), seed = q.id * 7;
      const M = [["On-time task completion", 70 + (seed % 28)], ["Meeting attendance", 66 + ((seed * 3) % 32)], ["Task follow-through (not reassigned)", 74 + ((seed * 5) % 24)], ["Deadline buffer (avg. early completion)", 55 + ((seed * 2) % 40)]];
      const overall = Math.round(M.reduce((a, b) => a + b[1], 0) / M.length);
      page = (<><Top title={`${q.name}'s Evaluation`} tag /><Ident q={q} />
        <div className="score"><div className="panel" style={{ textAlign: "center" }}><h3>Overall score</h3><div className="big">{overall}%</div><p>Based on placeholder metrics — backend supplies real data.</p></div>
          <div className="panel">{M.map(([k, v]) => <div key={k} style={{ marginBottom: 12 }}><div className="lbl">{k}: {v}%</div><div className="meter"><i style={{ width: `${v}%` }} /></div></div>)}</div></div>
        <div className="panel" style={{ marginTop: 18 }}><h3>Admin comments</h3><textarea className="field" placeholder="Write feedback for this member…" /><div style={{ textAlign: "center", marginTop: 10 }}><button className="btn" onClick={() => say("Evaluation saved (placeholder)")}>Save evaluation</button></div></div></>);
      break;
    }
    case "taskmetrics":
      page = <Grid title="Task Metrics" tag onPick={(q) => go("tm", { id: q.id })} extra={<div style={{ textAlign: "center", marginTop: 20 }}><button className="btn alt" onClick={() => go("reassigned")}>Tasks Re-assigned</button></div>} />;
      break;
    case "tm": {
      const q = person(p.id), done = TASKS.filter((t) => t.status === "Completed");
      page = (<><Top title={`${q.name}'s Task Metrics`} tag /><Ident q={q} /><h3 style={{ textAlign: "center", fontSize: 26, margin: "0 0 10px" }}>Tasks Completed: {done.length}</h3>
        {done.map((t) => <div className="due" key={t.id}><span style={{ width: 110, fontSize: 18 }}>{t.finished}:</span><button className="pill" onClick={() => go("task", { id: t.id })}>{t.title}</button></div>)}</>);
      break;
    }
    case "reassigned":
      page = (<><Top title={`Tasks Re-assigned: ${REQUESTS.length}`} tag />{REQUESTS.map((r) => <div className="due" key={r.id}><span style={{ width: 110, fontSize: 18 }}>11/1{r.id}/2026:</span><button className="pill" onClick={() => go("task", { id: r.task })}>{task(r.task).title}</button><span style={{ fontSize: 18, width: 230 }}>Assignee: {person(r.to).name}</span></div>)}</>);
      break;
    case "review":
      page = (<><Top title="Review Pending Task Re-assignments" tag />{reqs.map((r) => (<div className="req" key={r.id}><div className="panel">Task Re-assignment Request:<br />“{task(r.task).title}”<br />{person(r.from).name} → {person(r.to).name}</div>
        <button className="rb" style={{ background: "#4fae5e" }} aria-label="Approve" onClick={() => { setReqs(reqs.filter((x) => x.id !== r.id)); say("Approved — recipient will be notified"); }}>✓</button>
        <button className="rb" style={{ background: "#e5594f" }} aria-label="Deny" onClick={() => { setReqs(reqs.filter((x) => x.id !== r.id)); say("Request denied"); }}>✕</button></div>))}
        {!reqs.length && <p style={{ textAlign: "center", fontSize: 20 }}>No pending requests. New ones will appear here.</p>}</>);
      break;
    case "meetmetrics":
      page = <Grid title="Meeting Metrics" tag onPick={(q) => go("mm", { id: q.id })} />;
      break;
    case "mm": {
      const q = person(p.id);
      page = (<><Top title={`${q.name}'s Meeting Metrics`} tag /><Ident q={q} /><h3 style={{ textAlign: "center", fontSize: 26, margin: "0 0 10px" }}>Meetings Attended: {MEETINGS.length}</h3>
        {MEETINGS.map((m) => <div className="due" key={m.id}><span style={{ width: 110, fontSize: 18 }}>{m.date}:</span><button className="pill" style={{ textAlign: "center" }} onClick={() => go("meeting", { id: m.id })}>Review</button></div>)}</>);
      break;
    }
    default: page = null;
  }

  // The "Profiles" grid for admins opens a profile first, where clicking the name offers dashboard view
  return (
    <div className="app"><style>{CSS}</style>{page}
      {modal === "notif" && (<div className="modal"><div className="box"><h4>Incoming task from Sam Rivera:</h4>Task Reassignment Request:<br />Sam Rivera → {me.name}<br />“Allocate Budget for GBM 1”
        <div className="acts"><button className="btn out" onClick={() => { setModal(null); say("Task accepted"); }}>Accept</button><button className="btn out" onClick={() => { setModal(null); say("Task declined"); }}>Decline</button></div></div></div>)}
      {modal?.view && (<div className="modal"><div className="box">View {modal.view.name}’s page?<div className="acts"><button className="btn alt" onClick={() => setModal(null)}>Cancel</button>
        <button className="btn" onClick={() => { setViewAs(modal.view.id); setModal(null); setStack([{ n: "dash" }]); }}>Confirm</button></div></div></div>)}
      {modal?.reassign && (<div className="modal"><div className="box">Request to reassign “{modal.reassign[0].title}” to {modal.reassign[1].name}?<br /><small>Your request goes to an admin for approval.</small>
        <div className="acts"><button className="btn alt" onClick={() => setModal(null)}>Cancel</button><button className="btn" onClick={() => { setModal(null); say("Reassignment request sent to admin"); }}>Send request</button></div></div></div>)}
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}
