"use client";

import { SkillBrandIcon } from "./skill-icon";

const LEVEL_META: Record<string, { label: string; color: string; bar: string; glow: string; bars: number }> = {
  expert: { label: "Expert", color: "#D97706", bar: "#F59E0B", glow: "rgba(245,158,11,.4)", bars: 3 },
  advanced: { label: "Advanced", color: "#5448D4", bar: "#7B72E9", glow: "rgba(123,114,233,.35)", bars: 2 },
  intermediate: { label: "Mid", color: "#0284C7", bar: "#0EA5E9", glow: "rgba(14,165,233,.35)", bars: 1 },
  beginner: { label: "Beginner", color: "#059669", bar: "#10B981", glow: "rgba(16,185,129,.35)", bars: 1 },
};
const levelMeta = (l: string) => LEVEL_META[l.toLowerCase()] ?? LEVEL_META.intermediate;

export function SkillMatrix({ skills, embedded = false }: { skills: { name: string; level: string }[]; embedded?: boolean }) {
  const body = (
    <>
      {!embedded && (
        <div className="flex items-center justify-between mb-3">
          <span className="font-mono text-[11px] uppercase font-bold tracking-wider text-[#8E8E88]">Skill Matrix</span>
          <span className="font-mono text-[10px] text-[#7B72E9] font-bold">{skills.length} TRACKED</span>
        </div>
      )}
      <div className="grid grid-cols-3 gap-2 pf-skill-grid">
        {skills.map((skill) => {
          const meta = levelMeta(skill.level);
          return (
            <div
              key={skill.name}
              className="flex flex-col items-center text-center px-2 py-2.5 rounded-xl bg-white border border-[#e2e8f0]"
            >
              <SkillBrandIcon name={skill.name} size={28} />
              <span className="text-[11px] font-semibold text-[#0f172a] truncate max-w-full leading-tight mt-1.5" title={skill.name}>
                {skill.name}
              </span>
              <span className="inline-flex items-center gap-1 mt-1">
                <span className="font-mono text-[9px] font-bold" style={{ color: meta.color }}>{meta.label}</span>
                <span className="flex gap-[2px]" role="img" aria-label={`${meta.label}: ${meta.bars} of 3`}>
                  {[0, 1, 2].map((i) => (
                    <span
                      key={i}
                      className="w-1.5 h-1 rounded-sm"
                      style={i < meta.bars ? { background: meta.bar } : { background: "#E2E8F0" }}
                    />
                  ))}
                </span>
              </span>
            </div>
          );
        })}
      </div>
    </>
  );

  if (embedded) return <div id="skills">{body}</div>;
  return (
    <div className="bg-white border border-[#e2e8f0] rounded-[20px] p-5" id="skills">
      {body}
    </div>
  );
}
