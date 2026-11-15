import { useEffect, useMemo, useState } from "react";

// Fairy lights in the style of the WiCS posters: a thin tan wire swagged in connected U shapes,
// soft glowing yellow orbs, and a few hand-drawn sparkles. Swags and bulbs are slightly uneven on
// purpose (seeded, so they never jump around) so it reads as hung by hand, not stamped from a tile.

// <geometry>
const TOP = 10;
const rng = (seed) => () => {
  seed = (seed + 0x6d2b79f5) | 0;
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};
export function buildLights(width) {
  const r = rng(11), swags = [], bulbs = [], sparks = [];
  let x = -24;
  while (x < width + 24) {
    const w = 190 + r() * 80, d = 36 + r() * 30, x1 = x + w;
    swags.push({ x, x1, w, d });
    const c1x = x + w * 0.25, c2x = x + w * 0.75, cy = TOP + d * 1.333;
    const n = Math.max(3, Math.round(w / 46));
    for (let i = 0; i < n; i++) {
      const t = (i + 0.5 + (r() - 0.5) * 0.55) / n, u = 1 - t;
      const bx = u ** 3 * x + 3 * u * u * t * c1x + 3 * u * t * t * c2x + t ** 3 * x1;
      const by = u ** 3 * TOP + 3 * u * u * t * cy + 3 * u * t * t * cy + t ** 3 * TOP;
      const tilt = (r() - 0.5) * 0.5, hang = 7 + r() * 6, rad = 4.6 + r() * 2.2;
      bulbs.push({
        bx, by, ex: bx + Math.sin(tilt) * hang, ey: by + Math.cos(tilt) * hang + rad,
        rad, warm: r() > 0.16, dur: 2.4 + r() * 2.6, delay: -r() * 5,
      });
    }
    if (r() < 0.65) sparks.push({ x: x + w * (0.25 + r() * 0.5), y: TOP + d * (0.22 + r() * 0.22), s: 5 + r() * 4, dur: 2.8 + r() * 2.4, delay: -r() * 5 });
    x = x1;
  }
  return { swags, bulbs, sparks, end: x };
}
// </geometry>

const WIRE = "#a77b50";
const PIN = "#5a0d05";

export default function FairyLights() {
  const [width, setWidth] = useState(() => document.documentElement.clientWidth);
  useEffect(() => {
    const onResize = () => setWidth(document.documentElement.clientWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const bucket = Math.ceil(width / 200) * 200; // regenerate only in steps, so resizing doesn't reshuffle the lights
  const { swags, bulbs, sparks, end } = useMemo(() => buildLights(bucket), [bucket]);
  const wirePath = swags.map(({ x, x1, w, d }) =>
    `M${x.toFixed(1)} ${TOP}C${(x + w * 0.25).toFixed(1)} ${(TOP + d * 1.333).toFixed(1)} ${(x + w * 0.75).toFixed(1)} ${(TOP + d * 1.333).toFixed(1)} ${x1.toFixed(1)} ${TOP}`).join("");

  return (
    <div className="fairy-lights" aria-hidden="true">
      <style>{`
        .fairy-lights{position:absolute;top:0;left:0;width:100%;height:112px;overflow:hidden;pointer-events:none;z-index:8}
        body:has(.app.inner-page) .fairy-lights{display:none}
        .fairy-lights svg{display:block;overflow:visible}
        .fl-halo,.fl-core,.fl-spark{transform-box:fill-box;transform-origin:center}
        .fl-halo{animation:flHalo var(--d) ease-in-out infinite alternate}
        .fl-core{animation:flCore var(--d) ease-in-out infinite alternate}
        .fl-spark{animation:flSpark var(--d) ease-in-out infinite}
        @keyframes flHalo{from{opacity:.45;scale:.88}to{opacity:1;scale:1.1}}
        @keyframes flCore{from{filter:brightness(.94)}to{filter:brightness(1.1)}}
        @keyframes flSpark{0%,100%{opacity:.15;scale:.55;rotate:0deg}50%{opacity:1;scale:1.05;rotate:18deg}}
        @media(prefers-reduced-motion:reduce){.fl-halo,.fl-core,.fl-spark{animation:none}}
        .app.home-lights{padding-top:calc(var(--s5) + 44px)}
      `}</style>
      <svg width={end + 24} height="112" viewBox={`0 0 ${end + 24} 112`}>
        <defs>
          <radialGradient id="flCoreW" cx=".4" cy=".35" r=".75"><stop offset="0" stopColor="#fffdf0" /><stop offset=".55" stopColor="#ffe9a6" /><stop offset="1" stopColor="#ffcf70" /></radialGradient>
          <radialGradient id="flCoreB" cx=".4" cy=".35" r=".75"><stop offset="0" stopColor="#fff4ee" /><stop offset=".55" stopColor="#f8c2b0" /><stop offset="1" stopColor="#ee9a82" /></radialGradient>
          <radialGradient id="flHaloW"><stop offset="0" stopColor="#ffdf8c" stopOpacity=".6" /><stop offset="1" stopColor="#ffdf8c" stopOpacity="0" /></radialGradient>
          <radialGradient id="flHaloB"><stop offset="0" stopColor="#f6a58f" stopOpacity=".5" /><stop offset="1" stopColor="#f6a58f" stopOpacity="0" /></radialGradient>
        </defs>
        <path d={wirePath} fill="none" stroke={WIRE} strokeWidth="1.4" strokeLinecap="round" />
        {swags.map(({ x }, i) => <circle key={`pin${i}`} cx={x} cy={TOP} r="3.2" fill={PIN} />)}
        {bulbs.map((b, i) => (
          <g key={i} style={{ "--d": `${b.dur.toFixed(2)}s` }}>
            <line x1={b.bx} y1={b.by} x2={b.ex} y2={b.ey - b.rad} stroke={WIRE} strokeWidth="1.1" strokeLinecap="round" />
            <circle className="fl-halo" cx={b.ex} cy={b.ey} r={b.rad * 3.4} fill={b.warm ? "url(#flHaloW)" : "url(#flHaloB)"} style={{ animationDelay: `${b.delay.toFixed(2)}s` }} />
            <circle className="fl-core" cx={b.ex} cy={b.ey} r={b.rad} fill={b.warm ? "url(#flCoreW)" : "url(#flCoreB)"} style={{ animationDelay: `${b.delay.toFixed(2)}s` }} />
          </g>
        ))}
        {sparks.map((s, i) => (
          <g key={`s${i}`} transform={`translate(${s.x} ${s.y}) scale(${s.s})`} style={{ "--d": `${s.dur.toFixed(2)}s` }}>
            <path className="fl-spark" style={{ animationDelay: `${s.delay.toFixed(2)}s` }}
              d="M0 -1C.08 -.35 .35 -.08 1 0C.35 .08 .08 .35 0 1C-.08 .35 -.35 .08 -1 0C-.35 -.08 -.08 -.35 0 -1Z"
              fill="#ffe3a0" stroke="#e0b25a" strokeWidth=".14" />
          </g>
        ))}
      </svg>
    </div>
  );
}
