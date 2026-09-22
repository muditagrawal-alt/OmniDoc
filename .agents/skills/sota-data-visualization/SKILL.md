---
name: sota-data-visualization
description: >-
  Accessible, high-performance data visualization, chart selection, map compliance, and interactive graph architectures.
  Evaluates bundle budget, data volume, SSR, and screen-reader alternatives.
  Activate when implementing charts, metric dashboards, geospatial maps, knowledge graphs, or data tables.
---

# Accessible & High-Performance Data Visualization

## When to Use
Activate this skill whenever:
- Building analytical charts (bar, line, scatter, area, histogram, heatmap).
- Integrating interactive geospatial maps (pins, clusters, choropleths, geo-boundaries).
- Designing interactive knowledge graphs or network topology visualizers.
- Creating data tables with sorting, filtering, and virtualized scrolling.
- Rendering mathematical equations or scientific notation (KaTeX).
- Auditing existing data visualizations for accessibility, color-blind safety, and performance.

---

## 1. Library Selection Architecture
Choose libraries by systematically evaluating five technical criteria: **Rendering Volume (DOM vs Canvas/WebGL)**, **SSR Compatibility**, **Bundle Budget**, **Accessibility Primitives**, and **Interactivity Depth**.

| Category | Library | Primary Use Case & Trade-offs |
|---|---|---|
| **Declarative React Charts** | **Recharts** | Great for standard business metrics (< 1,000 data points). Clean JSX API. SVG-based; not suited for massive time-series datasets. |
| **Statistical / Exploratory** | **Observable Plot** | Fast, expressive statistical charts with small bundle footprint. Excellent SSR compatibility. |
| **High-Volume / Canvas** | **Chart.js** or **uPlot** | Canvas-rendered. Handles 10,000+ data points with 60fps panning/zooming. Ideal for streaming or telemetry. |
| **Network & Knowledge Graphs** | **@xyflow/react (React Flow)** | Interactive node-edge architectures, workflow builders, custom HTML nodes, pan/zoom. |
| **Geospatial Maps** | **MapLibre GL JS** / **Leaflet** | MapLibre for client-side vector styling and smooth rotation/tilt; Leaflet for lightweight raster maps. |
| **Data Tables** | **TanStack Table v8** | Headless, zero-style table logic. Supports virtualization, column sorting, filtering, and pagination. |
| **Mathematical Typesetting** | **KaTeX** | Ultra-fast LaTeX math rendering with minimal runtime footprint. |

---

## 2. Geospatial Map Compliance & Tile Realities
**Never claim third-party map tiles are unconditionally free or zero-cost.**
- **OpenStreetMap (OSM)**: The public OSM tile servers are funded by donations with a strict tile usage policy. Heavy automated scraping or high-volume production traffic is strictly forbidden. Always provide attribution: `© OpenStreetMap contributors`.
- **Carto / MapTiler / Stadia / Mapbox**: Provide vector/raster styles with free evaluation tiers, but enforce hard rate limits, API keys, and commercial thresholds.
- **Production Checklist**:
  1. Inspect expected monthly active users (MAU) and map view volume.
  2. Confirm whether self-hosted vector tiles (e.g. PMTiles on object storage / Cloudflare CDN) are required for high-traffic or offline deployments.
  3. Include required attribution visibly in the map viewport.

---

## 3. Mandatory Accessibility & Usability Standards

### A. Non-Color Encodings & Color-Blind Safety
Never rely solely on color to differentiate data series. Many users experience protanopia, deuteranopia, or tritanopia.
- Combine color with **dashed stroke patterns**, **distinct marker shapes** (circle, triangle, square), or **direct labels**.
- Ensure contrast between data elements and their background passes WCAG AA (at least 3:1 for graphical objects).

### B. Screen Reader & Tabular Alternatives
Charts are inherently visual. Provide equivalent text and tabular alternatives:
- Provide an `aria-label` or visually hidden summary explaining the key trend or conclusion (e.g. *"Revenue increased 14% over Q3, peaking at $1.2M in September"*).
- For complex statistical charts, offer a button to toggle or view an accessible data table (`<table className="sr-only">` or accessible modal).

### C. Keyboard Interaction & Focus
Interactive charts with tooltips or clickable data points must be keyboard accessible:
- Allow users to tab through data nodes or use arrow keys to inspect points.
- Display tooltips on keyboard focus, matching pointer hover behavior.

### D. Empty, Loading, and Error States
Every chart must handle all lifecycle states:
- **Loading**: Skeleton placeholder matching the chart dimensions to avoid layout shifts.
- **Error**: Clear notification with a retry action if the data query fails.
- **Empty / Zero Data**: Informative message explaining why no data exists, rather than an empty coordinate grid.

---

## 4. Presentation Simplicity: Direct Labeling
Do not force redundant legends, dense gridlines, or multi-nested tooltips when direct labeling is clearer:
- For simple line or bar charts with 1–3 series, place labels directly adjacent to the end of the line or above the bar.
- Omit decorative axis lines and secondary tick marks if they do not aid data interpretation.
- Sparklines and trend indicators often communicate trajectory faster than full-sized coordinate systems.

---

## 5. Practical Implementation Pattern (Accessible Chart with States)

```tsx
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip } from 'recharts';

interface ChartProps {
  data: Array<{ date: string; value: number }>;
  isLoading: boolean;
  error?: string | null;
}

export function MetricTrendChart({ data, isLoading, error }: ChartProps) {
  if (isLoading) {
    return <div className="h-64 rounded-lg bg-surface-raised animate-pulse" aria-label="Loading chart data" />;
  }

  if (error) {
    return (
      <div className="h-64 flex items-center justify-center rounded-lg border border-status-error/20 bg-status-error/5 p-4 text-sm text-status-error">
        Failed to load metric data. Please refresh.
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div className="h-64 flex items-center justify-center rounded-lg border border-border-subtle p-4 text-sm text-text-muted">
        No records found for the selected period.
      </div>
    );
  }

  return (
    <figure className="space-y-2">
      {/* Screen reader summary */}
      <figcaption className="sr-only">
        Trend showing metric values over time. Data ranges from {data[0].date} to {data[data.length - 1].date}.
      </figcaption>

      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
            <XAxis dataKey="date" stroke="currentColor" className="text-text-muted text-xs" />
            <YAxis stroke="currentColor" className="text-text-muted text-xs" />
            <Tooltip
              contentStyle={{
                backgroundColor: 'var(--bg-surface)',
                borderColor: 'var(--border-subtle)',
                color: 'var(--text-primary)',
                borderRadius: '8px',
              }}
            />
            <Line
              type="monotone"
              dataKey="value"
              stroke="var(--color-accent)"
              strokeWidth={2}
              dot={{ r: 3 }}
              activeDot={{ r: 6 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
```

---

## Strict Anti-Patterns
- ❌ **MISLEADING 3D CHARTS ARE STRICTLY BANNED**: Never use 3D pie charts, pseudo-3D bars, or perspective projections. They distort angles, foreshorten slices, and compromise data fidelity.
- ❌ Never claim map tiles or tile APIs are "100% free" without verifying TOS, usage tiers, and rate limits.
- ❌ Never rely exclusively on color hues to distinguish series or status.
- ❌ Never ship charts without handling loading, error, and empty zero-data states.
- ❌ Never omit accessible tabular alternatives or text summaries for critical data.
- ❌ Never clutter charts with unnecessary axes or legends when direct labeling is clearer.
