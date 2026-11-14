import { useEffect, useState } from 'react';
import { checkHealth } from './lib/api';

export default function App() {
  const [apiStatus, setApiStatus] = useState('Checking API…');

  useEffect(() => {
    const controller = new AbortController();
    checkHealth(controller.signal)
      .then(() => setApiStatus('API connected'))
      .catch(() => {
        if (!controller.signal.aborted) setApiStatus('API offline · start the backend');
      });
    return () => controller.abort();
  }, []);

  return (
    <main>
      <header>
        <a className="wordmark" href="/">winnie<span>✳</span></a>
        <span className="status" role="status">{apiStatus}</span>
      </header>
      <section className="intro">
        <p className="eyebrow">NJIT WOMEN IN COMPUTING SOCIETY</p>
        <h1>Big ideas.<br />Nothing dropped.</h1>
        <p className="subtitle">Your board’s shared picture of every event, every task, and the people making it happen.</p>
      </section>
      <section className="cards" aria-label="Planned dashboard features">
        <article><span>01 / PEOPLE</span><h2>The board</h2><p>Member profiles, skills, and a clear view of everyone’s workload.</p></article>
        <article><span>02 / PLANNING</span><h2>From meeting to momentum</h2><p>Turn transcripts into proposed tasks. Review the plan before it goes live.</p></article>
        <article><span>03 / FOLLOW-THROUGH</span><h2>One text away</h2><p>Check off tasks, ask for help, and keep the right people in the loop.</p></article>
      </section>
      <footer>HackPrinceton · Development scaffold · Features coming next</footer>
    </main>
  );
}
