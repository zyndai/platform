"use client";

// GitHub's official contribution graph colors (light theme)
const GH_GREEN = ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
// Day labels: only Mon/Wed/Fri shown (indices 1, 3, 5 in Sun-based week)
const DAY_LABELS = ["", "Mon", "", "Wed", "", "Fri", ""];

const CELL = 10; // px cell size
const GAP = 2;   // px gap between cells
const WEEK_W = CELL + GAP;
const DAY_LABEL_W = 22; // px for the day-label column

interface ContributionHeatmapProps {
  levels: number[];
  year: number;
  total: number;
  avgPerDay?: number | null;
}

export function ContributionHeatmap({ levels, year, total, avgPerDay }: ContributionHeatmapProps) {
  const numWeeks = Math.max(Math.floor(levels.length / 7), 26);
  const numDays = numWeeks * 7;

  // Align levels to full weeks; pad the front with 0s if shorter
  const padded: number[] =
    levels.length >= numDays
      ? levels.slice(-numDays)
      : [...Array(numDays - levels.length).fill(0), ...levels];

  // Group into columns (one column = one week)
  const weeks: number[][] = Array.from({ length: numWeeks }, (_, w) =>
    padded.slice(w * 7, w * 7 + 7)
  );

  // Derive the approximate start date to label months
  const endDate = new Date();
  const startDate = new Date(endDate);
  startDate.setDate(endDate.getDate() - numDays + 1);

  // Find the first column index of each month
  const monthPositions: { label: string; col: number }[] = [];
  let lastMonth = -1;
  for (let w = 0; w < numWeeks; w++) {
    const d = new Date(startDate);
    d.setDate(startDate.getDate() + w * 7);
    const m = d.getMonth();
    if (m !== lastMonth) {
      monthPositions.push({ label: MONTHS[m], col: w });
      lastMonth = m;
    }
  }

  const totalWidth = DAY_LABEL_W + numWeeks * WEEK_W;

  return (
    <div className="bg-[#f6f8fa] rounded-2xl border border-gray-200/60 p-3 mt-3">
      {/* Header */}
      <div className="flex items-center justify-between text-[9px] font-mono text-[#8E8E88] mb-2">
        <span>{total.toLocaleString()} contributions in {year}</span>
        {avgPerDay != null && avgPerDay > 0 && (
          <span>avg {avgPerDay}/day</span>
        )}
      </div>

      {/* Scrollable grid area */}
      <div className="overflow-x-auto pb-1">
        <div style={{ width: totalWidth, minWidth: totalWidth }}>
          {/* Month labels row */}
          <div className="flex text-[9px] font-mono text-[#57606a] mb-[3px] select-none" style={{ paddingLeft: DAY_LABEL_W }}>
            {monthPositions.map(({ label, col }, i) => {
              const nextCol = monthPositions[i + 1]?.col ?? numWeeks;
              const widthPx = (nextCol - col) * WEEK_W;
              return (
                <span
                  key={label + col}
                  style={{ width: widthPx, minWidth: widthPx, flexShrink: 0, overflow: "hidden", display: "block" }}
                >
                  {label}
                </span>
              );
            })}
          </div>

          {/* Day labels + week columns */}
          <div className="flex" style={{ gap: GAP }}>
            {/* Day labels */}
            <div
              className="flex flex-col shrink-0 select-none text-[8.5px] font-mono text-[#57606a]"
              style={{ gap: GAP, width: DAY_LABEL_W - GAP }}
            >
              {DAY_LABELS.map((label, i) => (
                <span
                  key={i}
                  style={{ height: CELL, lineHeight: `${CELL}px`, display: "block" }}
                >
                  {label}
                </span>
              ))}
            </div>

            {/* Week columns */}
            <div className="flex" style={{ gap: GAP }}>
              {weeks.map((week, wi) => (
                <div key={wi} className="flex flex-col" style={{ gap: GAP }}>
                  {week.map((lvl, di) => {
                    const idx = Math.min(Math.max(lvl || 0, 0), 4);
                    return (
                      <span
                        key={di}
                        className="block rounded-[2px]"
                        style={{ width: CELL, height: CELL, backgroundColor: GH_GREEN[idx] }}
                      />
                    );
                  })}
                </div>
              ))}
            </div>
          </div>

          {/* Legend */}
          <div className="flex items-center justify-end gap-[3px] mt-2 font-mono text-[8.5px] text-[#57606a] select-none">
            <span>Less</span>
            {GH_GREEN.map((color) => (
              <span
                key={color}
                className="block rounded-[2px]"
                style={{ width: CELL, height: CELL, backgroundColor: color }}
              />
            ))}
            <span>More</span>
          </div>
        </div>
      </div>
    </div>
  );
}
