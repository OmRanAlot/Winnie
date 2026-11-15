import { useEffect, useState } from "react";

// A tiny pixel heart and two sparkles pop up where you click. Skipped for reduced-motion users.
export default function CursorFx() {
  const [bursts, setBursts] = useState([]);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return undefined;
    let n = 0;
    const onDown = (e) => {
      if (e.button !== 0) return;
      const id = n++;
      setBursts((list) => [...list.slice(-5), { id, x: e.clientX, y: e.clientY }]);
    };
    window.addEventListener("pointerdown", onDown, true);
    return () => window.removeEventListener("pointerdown", onDown, true);
  }, []);
  return (
    <div className="cursor-fx" aria-hidden="true">
      {bursts.map((b) => (
        <span key={b.id} className="fx" style={{ left: b.x, top: b.y }}
          onAnimationEnd={() => setBursts((list) => list.filter((x) => x.id !== b.id))}>
          <i /><i /><i />
        </span>
      ))}
    </div>
  );
}