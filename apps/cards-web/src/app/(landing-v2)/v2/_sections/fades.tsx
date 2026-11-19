// Soft white glows the design layers over section seams. They sit above the
// sections they straddle, so they must render after them.
export function HowItWorksFade() {
  return <div aria-hidden className="bg-[#fffefe] blur-[85.5px] absolute left-[146px] top-[2110px] w-[1120px] h-[324px]" />;
}

export function CtaBannerFade() {
  return <div aria-hidden className="bg-[#fffefe] blur-[115.5px] absolute left-[247px] top-[4119px] w-[1087px] h-[324px]" />;
}
