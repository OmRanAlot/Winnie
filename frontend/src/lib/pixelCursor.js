// Pixel-art cursors drawn from tiny text maps. Edit the maps to redraw them.
// o = outline, f = fill, r = heart, y = star, w = star centre
const PALETTE = { o: "#5a0d05", f: "#fff3e2", r: "#e8756a", y: "#e0b25a", w: "#fff8f0" };

const pixelSvg = (rows, k = 2) => {
  const rects = rows.flatMap((row, y) => [...row].map((c, x) => PALETTE[c]
    ? `<rect x="${x * k}" y="${y * k}" width="${k}" height="${k}" fill="${PALETTE[c]}"/>` : "")).join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${rows[0].length * k}" height="${rows.length * k}" shape-rendering="crispEdges">${rects}</svg>`;
};
const dataUrl = (svg) => `url("data:image/svg+xml,${encodeURIComponent(svg)}")`;
// Paint `art` onto `rows` at (x0, y0); "." leaves the pixel alone.
const stamp = (rows, art, x0, y0) => rows.map((row, y) => {
  const a = art[y - y0];
  return a ? [...row].map((c, x) => (a[x - x0] && a[x - x0] !== "." ? a[x - x0] : c)).join("") : row;
});

const HEART = [".r.r.", "rrrrr", ".rrr.", "..r.."];
const STAR = ["..y..", "..y..", "yywyy", "..y..", "..y.."];

// Shapes are drawn as plain fill, then outlined automatically, so every edge gets the same clean 1px line.
const outline = (fill) => {
  const h = fill.length, w = Math.max(...fill.map((r) => r.length));
  const at = (x, y) => fill[y]?.[x] === "#";
  const rows = [];
  for (let y = -1; y <= h; y++) {
    let row = "";
    for (let x = -1; x <= w; x++) {
      row += at(x, y) ? "f" : (at(x + 1, y) || at(x - 1, y) || at(x, y + 1) || at(x, y - 1)) ? "o" : ".";
    }
    rows.push(row);
  }
  return rows;
};
// Fill every cell whose centre is inside the polygon.
const polygon = (pts, w, h) => Array.from({ length: h }, (_, y) => Array.from({ length: w }, (_, x) => {
  const px = x + 0.5, py = y + 0.5;
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i], [xj, yj] = pts[j];
    if ((yi > py) !== (yj > py) && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside ? "#" : ".";
}).join(""));

const ARROW = stamp(
  outline(polygon([[0, 0], [0, 16], [4, 12.4], [7.2, 19], [10, 17.8], [7, 11.4], [12, 11.2]], 13, 19)),
  HEART, 3, 8,
);

const HAND = stamp(outline([
  "....##.......",
  "...####......",
  "...####......",
  "...####......",
  "...####......",
  "...####.##...",
  "...####.####.",
  ".###########.",
  "#############",
  "#############",
  ".###########.",
  ".###########.",
  "..#########..",
  "...#######...",
]), HEART, 5, 9);

export const PIXEL_ARROW_CURSOR = `${dataUrl(pixelSvg(ARROW))} 2 2, auto`;
export const PIXEL_HAND_CURSOR = `${dataUrl(pixelSvg(HAND))} 11 2, pointer`;

// Subtle, stepped (pixel-feel) motion. Reduced-motion users get none of it:
// the app's global reduced-motion rule switches every animation off.
export const CUTE_CSS = `
@keyframes nudge{0%{rotate:0deg}30%{rotate:-1.6deg}65%{rotate:1.6deg}100%{rotate:0deg}}
@keyframes ring{0%,84%,100%{rotate:0deg}87%{rotate:14deg}90%{rotate:-12deg}93%{rotate:8deg}96%{rotate:-4deg}}
@keyframes badge{0%,100%{scale:1}50%{scale:1.18}}
@keyframes crumb{0%,100%{width:38px}50%{width:56px}}
@keyframes pageIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
@keyframes boxIn{from{opacity:0;transform:scale(.86)}to{opacity:1;transform:none}}
@keyframes toastIn{from{opacity:0;transform:translateX(-50%) translateY(14px)}to{opacity:1;transform:translateX(-50%)}}
@keyframes barIn{from{transform:scaleX(0)}to{transform:scaleX(1)}}
@keyframes fxUp{from{opacity:1;transform:translate(-50%,-50%) scale(.6)}to{opacity:0;transform:translate(calc(-50% + var(--dx)),calc(-50% - 30px)) scale(1)}}
.page-content{animation:pageIn .38s cubic-bezier(.2,.8,.2,1) both}
.app .btn:not(:disabled):hover,.app .nav button:hover{animation:nudge .42s steps(4) 1}
.bell svg{transform-origin:50% 8%;animation:ring 6s ease-in-out 1.5s infinite}
.bell b{animation:badge 2.4s steps(4) infinite}
.app.design-refresh .top h1::after{animation:crumb 4.5s steps(8) infinite}
.modal .box{animation:boxIn .24s cubic-bezier(.3,1.7,.5,1) both}
.toast{animation:toastIn .28s steps(5) both}
.bar{transform-origin:left center;animation:barIn .5s steps(8) both}
.gr:nth-child(2) .bar{animation-delay:.06s}.gr:nth-child(3) .bar{animation-delay:.12s}.gr:nth-child(4) .bar{animation-delay:.18s}.gr:nth-child(5) .bar{animation-delay:.24s}.gr:nth-child(n+6) .bar{animation-delay:.3s}
.metrics-member-link:hover .avatar{animation:nudge .42s steps(4) 1}
.status-switch.on .status-switch-track i{animation:badge .3s steps(3) 1}
.cursor-fx{position:fixed;inset:0;pointer-events:none;z-index:99}
.fx{position:absolute;width:0;height:0}
.fx i{position:absolute;left:0;top:0;background-repeat:no-repeat;background-size:100% 100%;image-rendering:pixelated;animation:fxUp .6s steps(6) forwards}
.fx i:nth-child(1){width:15px;height:12px;background-image:${dataUrl(pixelSvg(HEART, 3))};--dx:0px}
.fx i:nth-child(2){width:10px;height:10px;background-image:${dataUrl(pixelSvg(STAR, 2))};--dx:-18px;animation-delay:.05s}
.fx i:nth-child(3){width:10px;height:10px;background-image:${dataUrl(pixelSvg(STAR, 2))};--dx:18px;animation-delay:.1s}
`;