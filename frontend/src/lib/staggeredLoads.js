// Launch independent admin reads in a paced order. The first job is always first.
export function staggeredLoads(first, remaining, onStatus, { gapMs = 350, maxConcurrent = 2, random = Math.random } = {}) {
  const shuffled = [...remaining];
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  const jobs = [first, ...shuffled];
  const ready = new Set();
  const timers = [];
  let active = 0;
  let stopped = false;
  const launch = () => {
    if (stopped) return;
    for (let i = 0; i < jobs.length && active < maxConcurrent; i++) {
      if (!ready.has(i)) continue;
      ready.delete(i);
      const job = jobs[i];
      active++;
      onStatus(job.key, 'loading');
      Promise.resolve().then(job.run).then(
        () => { if (!stopped) onStatus(job.key, 'ready'); },
        () => { if (!stopped) onStatus(job.key, 'error'); },
      ).finally(() => { active--; launch(); });
    }
  };
  jobs.forEach((_, i) => timers.push(setTimeout(() => { ready.add(i); launch(); }, i * gapMs)));
  return () => { stopped = true; timers.forEach(clearTimeout); };
}
