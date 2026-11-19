// The design debosses white 400px text with an inner shadow. CSS text-shadow
// can't draw inside glyphs, so this is SVG text with an inner-shadow filter.
// Baseline 351 = Inter's ascent (0.969em) minus half of the negative leading
// a 1.028 line-height leaves on a 400px font, matching the Figma text box.
export function WordmarkSection() {
  return (
    <svg aria-hidden className="absolute left-[-4px] top-[10292px] overflow-visible" width={1460} height={411}>
      <defs>
        <filter id="landing-v2-wordmark-inset" x="-2%" y="-5%" width="104%" height="110%">
          <feComponentTransfer in="SourceAlpha" result="inverse">
            <feFuncA type="table" tableValues="1 0" />
          </feComponentTransfer>
          <feGaussianBlur in="inverse" stdDeviation="4" />
          <feOffset dx="2" dy="4" result="shadow" />
          <feFlood floodColor="#000" floodOpacity="0.3" />
          <feComposite in2="shadow" operator="in" />
          <feComposite in2="SourceAlpha" operator="in" result="inner" />
          <feMerge>
            <feMergeNode in="SourceGraphic" />
            <feMergeNode in="inner" />
          </feMerge>
        </filter>
      </defs>
      <text
        x={0}
        y={351}
        fill="#fff"
        filter="url(#landing-v2-wordmark-inset)"
        className="font-extrabold text-[400px] tracking-[-20px]"
        // Google Fonts' Inter sets this ~10px wider than the Inter build Figma renders with;
        // pinning the run length keeps the last "I" inside the 1440px canvas like the design.
        textLength={1441}
        lengthAdjust="spacing"
      >
        ZYNDAI
      </text>
    </svg>
  );
}
