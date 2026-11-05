/** Tiny inline SVG line chart (last ≤6 periods) shared by the comparison
 *  tables. Every point carries a hover hit-area whose native tooltip shows
 *  the period number and its value. Renders nothing when fewer than two
 *  points exist. */
export function Sparkline({
  values,
  color,
  lang = "en",
  width = 76,
  height = 22,
}: {
  values: number[];
  color: string;
  /** Tooltip language ("ar" | "en"). */
  lang?: string;
  width?: number;
  height?: number;
}) {
  const pad = 2;
  const n = values.length;
  if (n < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || Math.abs(max) || 1;
  const x = (i: number) => pad + (i * (width - 2 * pad)) / (n - 1);
  const y = (v: number) => height - pad - ((v - min) / span) * (height - 2 * pad);
  const pts = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const fmt = (v: number) =>
    new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(v);
  const label = (i: number) =>
    lang === "ar" ? `الفترة ${i + 1}: ${fmt(values[i])}` : `Period ${i + 1}: ${fmt(values[i])}`;
  // hover hit-area radius (bigger than the visible dot)
  const hit = 5;
  return (
    <svg
      className="spark"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden="true"
    >
      <polyline
        points={pts}
        fill="none"
        stroke={color}
        strokeWidth={1.6}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {values.map((v, i) => (
        <g key={i} className="spark-pt">
          <circle cx={x(i)} cy={y(v)} r={2.1} fill={color} />
          {/* transparent hit area — the native SVG tooltip lives here */}
          <circle cx={x(i)} cy={y(v)} r={hit} fill="transparent" className="spark-hit">
            <title>{label(i)}</title>
          </circle>
        </g>
      ))}
    </svg>
  );
}
