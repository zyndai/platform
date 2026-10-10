/** Design tokens + the onboarding stylesheet, extracted from page.tsx (S08
 *  PR0 split — no behaviour change). */
export const T = {
  page: "#E6E6E3",
  shell: "#F7F7F4",
  card: "#EFEFEB",
  surface: "#F7F7F4",
  accent: "#7B72E9",
  accentHi: "#6157DE",
  ink: "#0B0B0B",
  soft: "#6E6E68",
  muted: "#8E8E88",
  faint: "#A8A8A2",
  border: "#DEDED8",
  dashed: "#CFCFC8",
  dotOff: "#D6D6D0",
  onPanel: "#DCD8FF",
  onPanel2: "#C9C3FF",
  ctaOffBg: "#DDDAF8",
  ctaOffInk: "#9A94D8",
} as const;

const SANS = "var(--zc-sans), system-ui, -apple-system, sans-serif";
const DISPLAY = "var(--zc-display), system-ui, sans-serif";
const MONO = "var(--zc-mono), ui-monospace, monospace";

export const ZC_FONTS = { SANS, DISPLAY, MONO };

export const ZC_CSS = `
  /* The site-wide Webflow sheet styles bare h1/p/button and puts
     letter-spacing:-.05em on body — neutralise all of it inside this page. */
  .zc-root, .zc-root * { box-sizing: border-box; letter-spacing: normal; }
  .zc-root h1, .zc-root h2, .zc-root p { margin: 0; text-align: left; text-transform: none;
    background-image: none; -webkit-text-fill-color: currentColor; background-clip: border-box;
    -webkit-background-clip: border-box; font-weight: inherit; }
  .zc-root button, .zc-root input, .zc-root textarea { font-family: inherit; -webkit-appearance: none; appearance: none; }
  .zc-root input::placeholder, .zc-root textarea::placeholder { color: ${T.faint}; }

  .zc-root { height: 100dvh; background: ${T.page}; padding: 44px 36px 0; box-sizing: border-box; font-family: ${SANS}; color: ${T.ink}; line-height: 1.4; overflow: hidden; }
  .zc-shell { max-width: 1440px; width: 100%; margin-inline: auto; background: ${T.shell}; border-radius: 34px 34px 0 0; padding: 30px 32px 36px; display: flex; flex-direction: column; gap: 22px; box-sizing: border-box; height: 100%; overflow-y: auto; }
  .zc-grid { display: grid; grid-template-columns: 472px minmax(0,1fr); gap: 16px; align-items: stretch; flex: 1; min-height: 0; }
  .zc-panel { background: ${T.accent}; border-radius: 26px; padding: 34px 32px 30px; display: flex; flex-direction: column; gap: 30px; position: relative; overflow: hidden; min-height: 0; box-sizing: border-box; }
  /* globals.css sets \`h1,h2 { font-family/weight/transform ... !important }\`
     for the landing page — this panel opts out of that treatment. */
  .zc-root h1.zc-panel-title {
    font-family: ${DISPLAY} !important;
    font-weight: 700 !important;
    font-size: 54px;
    line-height: 1.02;
    text-transform: none !important;
    letter-spacing: -.035em !important;
    color: #fff; -webkit-text-fill-color: #fff;
  }
  .zc-col { display: flex; flex-direction: column; gap: 16px; min-width: 0; overflow-y: auto; }
  .zc-card { background: ${T.card}; border-radius: 26px; box-sizing: border-box; }
  .zc-step-card { flex: 1; }
  .zc-question { font: 700 34px/1.15 ${DISPLAY}; color: ${T.ink}; letter-spacing: -.03em; text-wrap: pretty; }
  .zc-ctarow { display: grid; grid-template-columns: minmax(0,1fr) 236px; gap: 16px; align-items: stretch; }

  .zc-back { transition: color .12s; }
  .zc-back:hover { color: ${T.ink} !important; text-decoration: none; }

  .zc-inputbox { transition: border-color .14s, box-shadow .14s; }
  .zc-inputbox:hover { border-color: ${T.faint}; }

  .zc-quick { transition: border-color .12s, color .12s; }
  .zc-quick:hover { border-color: ${T.accent} !important; }

  .zc-drop { transition: border-color .12s, background .12s; }
  .zc-drop:hover { border-color: ${T.accent} !important; }

  .zc-opt { transition: background .12s, border-color .12s, color .12s, transform .1s; cursor: pointer; }
  .zc-opt:hover { border-color: ${T.accent}; }
  .zc-opt:active { transform: scale(.97); }

  .zc-ghost { transition: border-color .12s, color .12s; }
  .zc-ghost:hover { border-color: ${T.ink} !important; color: ${T.ink} !important; }

  .zc-primary { transition: background .12s, transform .1s; }
  .zc-primary:hover:not(:disabled) { background: ${T.accentHi}; }
  .zc-primary:active:not(:disabled) { transform: translateY(1px); }

  .zc-cta { transition: background .12s, transform .1s; }
  .zc-cta:not(:disabled):hover { background: ${T.accentHi}; }
  .zc-cta:not(:disabled):active { transform: translateY(1px); }

  .zc-field:focus { border-color: ${T.accent}; }

  /* removable scraped rows (projects, posts, links) */
  .zc-row { background: ${T.surface}; border: 1px solid ${T.border}; border-radius: 16px;
    padding: 14px 16px; display: flex; align-items: flex-start; gap: 12px;
    transition: opacity .14s, border-color .14s; }
  .zc-row:hover { border-color: ${T.faint}; }
  .zc-row.off { opacity: .5; }
  .zc-row.off .zc-row-main { text-decoration: line-through; }
  .zc-rowbtn { background: none; border: none; padding: 0; cursor: pointer;
    font: 400 13px/1 ${SANS}; color: ${T.faint}; flex-shrink: 0; transition: color .12s; }
  .zc-rowbtn:hover { color: ${T.ink}; }
  .zc-clamp1, .zc-clamp2 { display: -webkit-box; -webkit-box-orient: vertical; overflow: hidden; }
  .zc-clamp1 { -webkit-line-clamp: 1; }
  .zc-clamp2 { -webkit-line-clamp: 2; }
  .zc-avatar { width: 56px; height: 56px; border-radius: 50%; object-fit: cover;
    border: 1px solid ${T.border}; flex-shrink: 0; display: block; }
  .zc-x { transition: color .12s; }
  .zc-x:hover { color: #fff !important; }

  @keyframes zc-chip-in { from { opacity: 0; transform: scale(.9) translateY(3px); } to { opacity: 1; transform: none; } }
  .zc-chip-enter { animation: zc-chip-in .18s cubic-bezier(.16,1,.3,1) both; }
  @keyframes zc-spin { to { transform: rotate(360deg); } }
  .zc-spin { animation: zc-spin .9s linear infinite; }

  @media (max-width: 1040px) {
    .zc-grid { grid-template-columns: minmax(0,1fr); }
    .zc-panel { padding: 28px 26px; gap: 24px; }
    .zc-root h1.zc-panel-title { font-size: 40px; }
    .zc-step-card { flex: none; }
    /* Stacked layout: let the page grow and scroll naturally. With the
       fixed-height shell the panel + form were squeezed into whatever
       height was left between the header and footer (the form ended up
       in a ~190px window scrolling inside itself). */
    .zc-root { height: auto; min-height: 100dvh; overflow: visible; display: flex; flex-direction: column; }
    .zc-shell { flex: 1 0 auto; height: auto; overflow: visible; }
    .zc-grid { flex: none; }
    .zc-col { overflow: visible; }
  }
  @media (max-width: 640px) {
    .zc-root { padding: 12px 10px 20px; }
    .zc-shell { border-radius: 26px; padding: 18px 12px 22px; gap: 16px; }
    .zc-grid, .zc-col { gap: 12px; }
    .zc-panel { border-radius: 22px; padding: 22px 18px 18px; gap: 18px; }
    .zc-root h1.zc-panel-title { font-size: 30px; }
    .zc-question { font-size: 26px; }
    .zc-card { border-radius: 22px; padding: 20px 18px !important; }
    .zc-live-card { padding: 28px 18px 24px !important; gap: 18px !important; }
    .zc-ctarow { grid-template-columns: minmax(0,1fr); gap: 12px; }
    .zc-inputbox { padding: 14px 16px !important; }
    .zc-cta { padding: 20px 22px !important; }

    /* never overflow sideways: long URLs / handles / error text wrap */
    .zc-root p, .zc-root h1, .zc-root .zc-question, .zc-row-main { overflow-wrap: anywhere; }
    .zc-chipbox { max-width: 100%; min-width: 0; }
    .zc-clip { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    /* 16px+ inputs — iOS Safari zooms the page on focus below that */
    .zc-root input:not([type="file"]), .zc-root textarea { font-size: 16px !important; min-width: 0; }

    /* tap targets: grow the hit area of tiny text buttons without moving
       anything (padding out, matching negative margin back in) */
    .zc-x, .zc-rowbtn, .zc-tap { padding: 14px 12px !important; margin: -14px -12px !important; }
    .zc-tap-end { margin-left: auto !important; }
    .zc-btn, .zc-quick { min-height: 40px; }
    .zc-dirlink { padding: 13px 6px; margin: -13px -6px; }
    .zc-pencil::after { content: ""; position: absolute; inset: -10px; }
    .zc-photo-actions { gap: 24px !important; }

    /* header / panel */
    .zc-badge { padding: 8px 13px !important; max-width: 100%; }
    .zc-badge-text { letter-spacing: .1em !important; line-height: 1.35 !important; }
    .zc-panel-live { flex-wrap: wrap; gap: 8px 12px !important; }
    .zc-handle-pill { max-width: 100%; overflow-wrap: anywhere; line-height: 1.35 !important; }

    /* questions */
    .zc-chips { gap: 8px !important; }
    .zc-chips .zc-opt:not([aria-label]) { padding: 12px 15px !important; }
    .zc-custom-input { flex: 1 1 140px; width: auto !important; }
    .zc-bigfield { padding: 16px !important; border-radius: 16px !important; }
    .zc-navrow, .zc-navgroup { gap: 8px !important; }
    .zc-navrow button { padding: 13px 16px !important; }

    /* post-publish */
    .zc-live-pill { max-width: 100%; padding: 6px 6px 6px 16px !important; gap: 8px !important; }
    .zc-live-url { min-width: 0; overflow-wrap: anywhere; font-size: 13px !important; line-height: 1.35 !important; text-align: left; }
    .zc-copy { min-height: 40px; padding: 0 16px !important; }

    /* review */
    .zc-fixrow { flex-wrap: wrap !important; }
    .zc-fixrow input { flex: 1 1 100% !important; }
    .zc-row-post { flex-wrap: wrap; row-gap: 6px; }
    .zc-row-label { width: auto !important; flex-basis: 100%; padding-top: 0 !important; }
    .zc-headrow { flex-wrap: wrap; gap: 6px 12px; }
    .zc-addrow { flex-wrap: wrap; }
    .zc-addbox { flex: 1 1 100% !important; padding: 12px 14px !important; }
    .zc-addrow > button { flex: 1 1 100% !important; }
    /* custom-handle field: prefix above the input so long slugs have room */
    .zc-handle-prefix { position: static !important; transform: none !important; margin-bottom: 8px; font-size: 13px !important; }
    .zc-handle-input { padding: 13px 92px 13px 15px !important; }
    .zc-handle-status { top: auto !important; bottom: 18px !important; transform: none !important; }

    /* footer: stack the tagline and the three steps */
    .zc-foot { flex-direction: column; align-items: flex-start !important; gap: 16px !important; padding-top: 16px !important; }
    .zc-foot-tag { padding-right: 0 !important; margin-right: 0 !important; border-right: none !important; }
    .zc-foot-steps { flex: none !important; flex-direction: column; gap: 14px !important; width: 100%; }
    .zc-foot-step { flex: none !important; padding-left: 0 !important; margin-left: 0 !important; border-left: none !important; }
  }
  @media (prefers-reduced-motion: reduce) {
    .zc-chip-enter { animation: none; }
    .zc-spin { animation-duration: 1.6s; }
  }
`;