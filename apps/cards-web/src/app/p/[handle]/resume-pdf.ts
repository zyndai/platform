/**
 * Client-side resume renderer for a published profile card.
 *
 * Only the résumé-relevant slice of the card makes it in — identity, summary,
 * skill matrix, work history and shipped projects. Social stats, writing
 * samples and the obsession cards stay on the profile page.
 *
 * jsPDF is imported lazily by the caller's click handler so it never lands in
 * the profile page bundle.
 */

export interface ResumeWorkItem {
  title?: string;
  company?: string;
  employment_type?: string;
  start_date?: string;
  end_date?: string;
  duration?: string;
  location?: string;
  description?: string;
}

export interface ResumeProject {
  name: string;
  description?: string | null;
  url?: string | null;
  tech?: string[] | null;
  stars?: number | null;
}

export interface ResumeData {
  name: string;
  headline?: string | null;
  location?: string | null;
  summary?: string | null;
  experienceYears?: number | null;
  profileUrl: string;
  links: Array<{ platform: string; url: string }>;
  skills: Array<{ name: string; level: string }>;
  work: ResumeWorkItem[];
  projects: ResumeProject[];
}

/* ─── palette (mirrors the profile page) ──────────────────────────────────── */

const INK = "#0B0B0B";
const SLATE = "#334155";
const MUTED = "#64748b";
const ACCENT = "#6d64f6";
const RULE = "#e2e8f0";

const LEVEL_META: Record<string, { label: string; color: string; bars: number }> = {
  expert: { label: "Expert", color: "#D97706", bars: 3 },
  advanced: { label: "Advanced", color: "#5448D4", bars: 2 },
  intermediate: { label: "Mid", color: "#0284C7", bars: 1 },
  beginner: { label: "Beginner", color: "#059669", bars: 1 },
};
const levelMeta = (l: string) => LEVEL_META[(l || "").toLowerCase()] ?? LEVEL_META.intermediate;

/* ─── helpers ─────────────────────────────────────────────────────────────── */

function isBlank(s: string | null | undefined): boolean {
  if (!s) return true;
  const low = s.toLowerCase().trim();
  return low === "" || low === "n/a" || low === "not specified" || low === "unknown" || low === "none";
}

/**
 * jsPDF's built-in Helvetica is WinAnsi-encoded, so anything outside cp1252
 * (emoji, CJK, arrows, box drawing) renders as garbage. Map the few symbols we
 * emit ourselves, then drop or decompose whatever the font cannot represent.
 */
const WINANSI_EXTRA = new Set([
  0x20ac, 0x201a, 0x0192, 0x201e, 0x2026, 0x2020, 0x2021, 0x02c6, 0x2030, 0x0160,
  0x2039, 0x0152, 0x017d, 0x2018, 0x2019, 0x201c, 0x201d, 0x2022, 0x2013, 0x2014,
  0x02dc, 0x2122, 0x0161, 0x203a, 0x0153, 0x017e, 0x0178,
]);

const representable = (ch: string): boolean => {
  const c = ch.codePointAt(0) ?? 0;
  return (c >= 0x20 && c <= 0xff && c !== 0x7f) || WINANSI_EXTRA.has(c);
};

/** Latin letters that have no cp1252 equivalent and do not decompose. */
const TRANSLITERATE: Record<string, string> = {
  "\u0141": "L", "\u0142": "l", "\u0110": "D", "\u0111": "d",
  "\u0126": "H", "\u0127": "h", "\u014a": "N", "\u014b": "n",
  "\u0166": "T", "\u0167": "t", "\u0131": "i", "\u0138": "k",
};

function pdfSafe(s: string): string {
  let out = "";
  for (const ch of s.replace(/[\u2192\u27a1]/g, "->").replace(/[\u2190]/g, "<-")) {
    const mapped = TRANSLITERATE[ch];
    if (mapped) {
      out += mapped;
      continue;
    }
    if (representable(ch)) {
      out += ch;
      continue;
    }
    // "Ā" → "A": keep the base letter when the char decomposes into one
    for (const part of ch.normalize("NFD")) if (representable(part)) out += part;
  }
  return out;
}

function clean(s: string | null | undefined): string {
  return pdfSafe((s ?? "").replace(/\s+/g, " ").trim());
}

function prettyUrl(url: string): string {
  return pdfSafe(url.replace(/^https?:\/\//, "").replace(/^www\./, "").replace(/\/+$/, ""));
}

function dateRange(job: ResumeWorkItem): string {
  const start = clean(job.start_date);
  const end = clean(job.end_date);
  const range = start ? `${start} – ${end || "Present"}` : end;
  const dur = clean(job.duration);
  if (range && dur) return `${range}  ·  ${dur}`;
  return range || dur;
}

/** LinkedIn descriptions arrive as newline- or bullet-separated blobs. */
function descriptionLines(raw: string | null | undefined): string[] {
  if (isBlank(raw)) return [];
  return (raw as string)
    .split(/\r?\n|(?:\s+[•·▪]\s+)/)
    .map((l) => pdfSafe(l.replace(/^[•·▪\-–]\s*/, "").trim()))
    .filter(Boolean);
}

/* ─── builder ─────────────────────────────────────────────────────────────── */

export async function buildResumePdf(data: ResumeData): Promise<Blob> {
  const { jsPDF } = await import("jspdf");
  const doc = new jsPDF({ unit: "pt", format: "a4", compress: true });

  const PW = doc.internal.pageSize.getWidth();
  const PH = doc.internal.pageSize.getHeight();
  const M = 48;
  const CW = PW - M * 2;
  const BOTTOM = PH - 56;

  let y = M;

  const font = (weight: "normal" | "bold", size: number, color: string) => {
    doc.setFont("helvetica", weight);
    doc.setFontSize(size);
    doc.setTextColor(color);
  };

  /** Break to a new page when `h` more points would run past the footer. */
  const ensure = (h: number) => {
    if (y + h > BOTTOM) {
      doc.addPage();
      y = M;
      return true;
    }
    return false;
  };

  const paragraph = (text: string, size: number, color: string, lead: number, weight: "normal" | "bold" = "normal", width = CW, x = M) => {
    font(weight, size, color);
    for (const line of doc.splitTextToSize(text, width) as string[]) {
      ensure(lead);
      doc.text(line, x, y);
      y += lead;
    }
  };

  const section = (title: string) => {
    ensure(52);
    y += 20;
    font("bold", 8.5, ACCENT);
    doc.setCharSpace(1.1);
    doc.text(title.toUpperCase(), M, y);
    doc.setCharSpace(0);
    y += 6;
    doc.setDrawColor(RULE);
    doc.setLineWidth(0.8);
    doc.line(M, y, M + CW, y);
    y += 14;
  };

  /* ── header ── */

  font("bold", 23, INK);
  doc.text(clean(data.name) || "Profile", M, y + 6);
  y += 14;

  if (!isBlank(data.headline)) {
    y += 16;
    paragraph(clean(data.headline), 11, ACCENT, 14, "bold");
    y -= 14;
  }

  const meta = [
    clean(data.location),
    data.experienceYears ? `${data.experienceYears}+ yrs experience` : "",
  ].filter(Boolean);
  if (meta.length) {
    y += 16;
    font("normal", 9, MUTED);
    doc.text(meta.join("   ·   "), M, y);
  }

  // Wrapped by whole links, so a separator never dangles at a line end.
  const linkParts = data.links.map((l) => prettyUrl(l.url)).filter(Boolean);
  if (linkParts.length) {
    y += 13;
    font("normal", 8.5, SLATE);
    const SEP = "   ·   ";
    let line = "";
    for (const part of linkParts) {
      const next = line ? line + SEP + part : part;
      if (line && doc.getTextWidth(next) > CW) {
        doc.text(line, M, y);
        y += 11;
        line = part;
      } else {
        line = next;
      }
    }
    if (line) doc.text(line, M, y);
  }

  y += 12;
  doc.setDrawColor(ACCENT);
  doc.setLineWidth(1.6);
  doc.line(M, y, M + CW, y);
  y += 4;

  /* ── summary ── */

  if (!isBlank(data.summary)) {
    section("Summary");
    paragraph(clean(data.summary), 9.8, SLATE, 14);
  }

  /* ── skill matrix ── */

  if (data.skills.length) {
    section("Skill Matrix");

    const COLS = 3;
    const GUT = 14;
    const colW = (CW - GUT * (COLS - 1)) / COLS;
    const rowH = 25;

    for (let i = 0; i < data.skills.length; i += COLS) {
      ensure(rowH);
      const rowTop = y;
      data.skills.slice(i, i + COLS).forEach((skill, c) => {
        const x = M + c * (colW + GUT);
        const m = levelMeta(skill.level);

        font("bold", 8.2, INK);
        doc.text(doc.splitTextToSize(clean(skill.name), colW)[0], x, rowTop);

        font("normal", 6.8, m.color);
        const label = m.label.toUpperCase();
        doc.text(label, x, rowTop + 9.5);

        // three-segment strength bar, matching the on-page skill matrix
        const barX = x + doc.getTextWidth(label) + 5;
        for (let b = 0; b < 3; b++) {
          doc.setFillColor(b < m.bars ? m.color : RULE);
          doc.roundedRect(barX + b * 7, rowTop + 5.6, 5.2, 3.2, 1, 1, "F");
        }
      });
      y = rowTop + rowH;
    }
    y -= 8;
  }

  /* ── work experience ── */

  const work = data.work.filter((j) => !isBlank(j.title) || !isBlank(j.company));
  if (work.length) {
    section("Work Experience");

    work.forEach((job, idx) => {
      ensure(46);
      const dates = dateRange(job);

      font("normal", 8.5, MUTED);
      const datesW = dates ? doc.getTextWidth(dates) : 0;
      font("bold", 10.5, INK);
      const titleW = CW - (datesW ? datesW + 16 : 0);
      doc.text(doc.splitTextToSize(clean(job.title) || clean(job.company), titleW)[0], M, y);
      if (dates) {
        font("normal", 8.5, MUTED);
        doc.text(dates, M + CW, y, { align: "right" });
      }
      y += 13;

      const sub = [clean(job.company), clean(job.employment_type), clean(job.location)]
        .filter((s, i) => Boolean(s) && !(i === 0 && isBlank(job.title)))
        .join("   ·   ");
      if (sub) {
        font("normal", 9.3, ACCENT);
        doc.text(doc.splitTextToSize(sub, CW)[0], M, y);
        y += 13;
      }

      const bullets = descriptionLines(job.description);
      if (bullets.length) {
        y += 2;
        for (const b of bullets) {
          font("normal", 9, SLATE);
          const lines = doc.splitTextToSize(b, CW - 12) as string[];
          lines.forEach((line, li) => {
            ensure(12.5);
            if (li === 0) {
              font("normal", 9, MUTED);
              doc.text("•", M, y);
            }
            font("normal", 9, SLATE);
            doc.text(line, M + 12, y);
            y += 12.5;
          });
        }
      }

      if (idx < work.length - 1) y += 12;
    });
  }

  /* ── live in production ── */

  if (data.projects.length) {
    section("Live in Production");

    data.projects.forEach((proj, idx) => {
      ensure(40);
      const stars = proj.stars && proj.stars > 0 ? `${proj.stars} stars` : "";

      font("bold", 8.5, "#c2410c");
      const starsW = stars ? doc.getTextWidth(stars) : 0;
      font("bold", 10, INK);
      doc.text(doc.splitTextToSize(clean(proj.name), CW - (starsW ? starsW + 16 : 0))[0], M, y);
      if (stars) {
        font("bold", 8.5, "#c2410c");
        doc.text(stars, M + CW, y, { align: "right" });
      }
      y += 12;

      if (!isBlank(proj.description)) {
        paragraph(clean(proj.description), 9, SLATE, 12);
      }

      const tech = (proj.tech ?? []).filter(Boolean);
      const url = proj.url ? prettyUrl(proj.url) : "";
      const tail = pdfSafe([tech.join(" · "), url].filter(Boolean).join("   —   "));
      if (tail) {
        ensure(12);
        font("normal", 8, MUTED);
        doc.text(doc.splitTextToSize(tail, CW)[0], M, y);
        y += 12;
      }

      if (idx < data.projects.length - 1) y += 8;
    });
  }

  /* ── footers ── */

  const pages = doc.getNumberOfPages();
  for (let p = 1; p <= pages; p++) {
    doc.setPage(p);
    doc.setDrawColor(RULE);
    doc.setLineWidth(0.6);
    doc.line(M, PH - 44, M + CW, PH - 44);
    font("normal", 7.8, MUTED);
    doc.text(`Live profile · ${prettyUrl(data.profileUrl)}`, M, PH - 30);
    doc.text(`${p} / ${pages}`, M + CW, PH - 30, { align: "right" });
  }

  return doc.output("blob");
}
