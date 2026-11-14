import React, { useEffect } from "react";
import { createRoot } from "react-dom/client";
import SessionGate from "./auth/SessionGate.jsx";

function ButtonClickBurst() {
  useEffect(() => {
    const handleClick = (event) => {
      if (!(event.target instanceof Element)) return;
      const button = event.target.closest("button");
      if (!button || button.disabled || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

      const rect = button.getBoundingClientRect();
      const rootRect = document.documentElement.getBoundingClientRect();
      if (getComputedStyle(button).textDecorationLine.includes("underline")) {
        const range = document.createRange();
        range.selectNodeContents(button);
        const textRect = range.getBoundingClientRect();
        if (textRect.width) {
          const line = document.createElement("span");
          line.setAttribute("aria-hidden", "true");
          Object.assign(line.style, {
            position: "fixed",
            display: "block",
            left: `${textRect.left - rootRect.left - 1}px`,
            top: `${textRect.bottom - rootRect.top + 4}px`,
            width: `${textRect.width + 2}px`,
            height: "2px",
            borderRadius: "999px",
            background: getComputedStyle(button).color,
            transformOrigin: "left center",
            pointerEvents: "none",
            zIndex: "9999",
          });
          document.body.appendChild(line);
          line.animate(
            [
              { opacity: 0, transform: "scaleX(0)" },
              { opacity: 0.65, transform: "scaleX(1)", offset: 0.4 },
              { opacity: 0, transform: "scaleX(1)" },
            ],
            { duration: 380, easing: "ease-out", fill: "forwards" },
          );
          window.setTimeout(() => line.remove(), 420);
          return;
        }
      }

      const burst = document.createElement("span");
      burst.setAttribute("aria-hidden", "true");
      Object.assign(burst.style, {
        position: "fixed",
        display: "block",
        left: `${rect.left + rect.width / 2 - rootRect.left}px`,
        top: `${rect.top + rect.height / 2 - rootRect.top}px`,
        width: "0",
        height: "0",
        overflow: "visible",
        pointerEvents: "none",
        zIndex: "9999",
      });
      document.body.appendChild(burst);

      const points = [0.18, 0.5, 0.82];
      const halfWidth = rect.width / 2;
      const halfHeight = rect.height / 2;
      const particles = [
        ...points.map((point) => ({ x: (point - 0.5) * rect.width, y: -halfHeight, angle: -90 })),
        ...points.map((point) => ({ x: (point - 0.5) * rect.width, y: halfHeight, angle: 90 })),
        ...points.map((point) => ({ x: -halfWidth, y: (point - 0.5) * rect.height, angle: 180 })),
        ...points.map((point) => ({ x: halfWidth, y: (point - 0.5) * rect.height, angle: 0 })),
      ];

      particles.forEach(({ x, y, angle }, index) => {
        const spark = document.createElement("i");
        const rotation = angle + (Math.random() - 0.5) * 18;
        const distance = 10 + Math.random() * 8;
        const radians = (rotation * Math.PI) / 180;
        const dx = Math.cos(radians) * distance;
        const dy = Math.sin(radians) * distance;
        const dot = index % 3 === 1;
        const width = dot ? 4 : 8;
        const height = dot ? 4 : 2;
        Object.assign(spark.style, {
          position: "absolute",
          left: `${x - width / 2}px`,
          top: `${y - height / 2}px`,
          width: `${width}px`,
          height: `${height}px`,
          borderRadius: "999px",
          background: "#17110f",
        });
        burst.appendChild(spark);
        spark.animate(
          [
            { opacity: 0, transform: `translate(0, 0) rotate(${rotation}deg) scale(0.5)` },
            { opacity: 1, transform: `translate(${dx * 0.3}px, ${dy * 0.3}px) rotate(${rotation}deg) scale(1)`, offset: 0.18 },
            { opacity: 0, transform: `translate(${dx}px, ${dy}px) rotate(${rotation}deg) scale(0.7)` },
          ],
          { duration: 460, easing: "cubic-bezier(0.16, 1, 0.3, 1)", fill: "forwards" },
        );
      });

      window.setTimeout(() => burst.remove(), 500);
    };

    document.addEventListener("click", handleClick, true);
    return () => document.removeEventListener("click", handleClick, true);
  }, []);

  return null;
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ButtonClickBurst />
    <SessionGate />
  </React.StrictMode>,
);
