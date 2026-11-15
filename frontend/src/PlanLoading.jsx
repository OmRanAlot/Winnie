import { useEffect, useState } from "react";

export default function PlanLoading() {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, []);

  return <div className="plan-loading">
    <div className="plan-loading-paper" aria-hidden="true">
      <span>✦</span>
      {[0, 1, 2].map(row => <i key={row} style={{ "--row": row }}><b /> <em /></i>)}
    </div>
    <div className="plan-loading-copy" role="status" aria-live="polite">
      <strong>Winnie is shaping your event plan</strong>
      <p>{seconds < 30
        ? "Drafting tasks, suggested roles, and dates for your idea."
        : "Still working on your draft. You can review and edit it next."}</p>
      <small>We’ll stop waiting after 90 seconds if it takes too long.</small>
    </div>
    <span className="plan-loading-time" aria-label={`${seconds} seconds elapsed`}>{seconds}s</span>
  </div>;
}
