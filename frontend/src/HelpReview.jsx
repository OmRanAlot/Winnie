import { useState } from "react";
import { reviewHelpRequests, decideHelpRequest } from "./lib/api.js";

// Uses the signed-in administrator's verified access token.
export default function HelpReview({ people = [] }) {
  const [requests, setRequests] = useState(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const name = code => people.find(person => person.id === code)?.name || code;
  async function load() {
    setBusy(true); setMessage("");
    try { setRequests(await reviewHelpRequests()); }
    catch (error) { setRequests(null); setMessage(error.message); }
    finally { setBusy(false); }
  }
  async function decide(request, action) {
    setBusy(true); setMessage("");
    try {
      const result = await decideHelpRequest(request.request_no, request.revision, action);
      setMessage(result.reply);
      setRequests(await reviewHelpRequests());
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }
  return <section>
    <p>Review ownership transfers requested through Winnie.</p>
    <button className="btn" disabled={busy} onClick={load}>Load requests</button>
    <p role="status">{message}</p>
    {requests?.map(request => <div className="panel" key={request.request_no}>
      <h3>HELP-{request.request_no}: {request.task?.title || "Task reassignment"}</h3>
      <p>{name(request.requester_code)} → {name(request.selected_code)}</p>
      <p>Approving transfers ownership. A handoff chat is created when group messaging is available.</p>
      <button className="btn" disabled={busy} onClick={() => decide(request, "approve")}>Approve transfer</button>{" "}
      <button className="btn alt" disabled={busy} onClick={() => decide(request, "deny")}>Deny</button>
    </div>)}
    {requests?.length === 0 && <p>No requests awaiting approval.</p>}
  </section>;
}
