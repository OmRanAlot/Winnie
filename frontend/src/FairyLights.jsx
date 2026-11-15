import { useEffect, useState } from "react";

// Strands of fairy lights drape across the top of the screen in connected U shapes.
// Drawn as SVG (not a photo) so it stays sharp at any size and the bulbs can twinkle.
const TILE = 220;                                   // width of one U
const CTRL = [[0, 8], [50, 74], [170, 74], [220, 8]]; // cubic curve that makes the U
const BULB_AT = [0.1, 0.3, 0.5, 0.7, 0.9];          // where bulbs hang along each U
const COLORS = ["#ffe3a0", "#f6b3a0", "#ffd070", "#fff3d0", "#f4a58f"];
const WIRE = "#5a0d05";

const pointAt = (t) => {
  const u = 1 - t;
  return [0, 1].map((i) => u * u * u * CTRL[0][i] + 3 * u * u * t * CTRL[1][i] + 3 * u * t * t * CTRL[2][i] + t * t * t * CTRL[3][i]);
};

export default function FairyLights() {
  const [width, setWidth] = useState(() => document.documentElement.clientWidth);
  useEffect(() => {
    const onResize = () => setWidth(document.documentElement.clientWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const tiles = Math.ceil(width / TILE) + 1;
  const offset = -((tiles * TILE - width) / 2); // centre the pattern so both edges look the same
  const path = Array.from({ length: tiles }, (_, k) => {
    const x = k * TILE;
    return `M${x} 8C${x + 50} 74 ${x + 170} 74 ${x + 220} 8`;
  }).join("");

  return (
    <div className="fairy-lights" aria-hidden="true">
      <style>{`
        .fairy-lights{position:absolute;top:0;left:50%;width:100vw;height:92px;overflow:hidden;pointer-events:none;z-index:4;transform:translateX(-50%)}
        .fairy-lights svg{display:block;overflow:visible}
        .fl-glow{animation:flGlow 3.2s ease-in-out infinite alternate}
        @keyframes flGlow{from{opacity:.18}to{opacity:.62}}
        .fl-bulb{animation:flBulb 3.2s ease-in-out infinite alternate}
        @keyframes flBulb{from{filter:brightness(.92)}to{filter:brightness(1.12)}}
        @media(prefers-reduced-motion:reduce){.fl-glow,.fl-bulb{animation:none}}
        .app.home-lights{padding-top:calc(var(--s5) + 44px)}
      `}</style>
      <svg width={tiles * TILE} height="92" viewBox={`0 0 ${tiles * TILE} 92`} style={{ marginLeft: offset }}>
        <path d={path} fill="none" stroke={WIRE} strokeWidth="1.8" strokeLinecap="round" />
        {Array.from({ length: tiles + 1 }, (_, k) => (
          <rect key={`clip${k}`} x={k * TILE - 3.5} y="3" width="7" height="10" rx="2" fill="#b5472a" stroke={WIRE} strokeWidth="1.2" />
        ))}
        {Array.from({ length: tiles }, (_, k) => BULB_AT.map((t, i) => {
          const [bx, by] = pointAt(t);
          const n = k * BULB_AT.length + i;
          const color = COLORS[n % COLORS.length];
          const delay = `${((n * 0.7) % 3.2).toFixed(2)}s`;
          return (
            <g key={`${k}-${i}`} transform={`translate(${k * TILE + bx} ${by})`}>
              <circle className="fl-glow" cy="14" r="17" fill={color} style={{ animationDelay: delay }} />
              <rect x="-2.5" y="0" width="5" height="6" rx="1.2" fill={WIRE} />
              <g className="fl-bulb" style={{ animationDelay: delay }}>
                <ellipse cy="14" rx="5.6" ry="7.4" fill={color} stroke={WIRE} strokeOpacity=".4" strokeWidth="1" />
                <ellipse cx="-1.8" cy="11.5" rx="1.4" ry="2.4" fill="#fff" opacity=".7" />
              </g>
            </g>
          );
        }))}
      </svg>
    </div>
  );
}
