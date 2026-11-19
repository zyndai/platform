import { CtaBannerSection } from "./_sections/cta-banner";
import { DiscoverSection } from "./_sections/discover";
import { ExploreSection } from "./_sections/explore";
import { CtaBannerFade, HowItWorksFade } from "./_sections/fades";
import { FaqSection } from "./_sections/faq";
import { HeroSection } from "./_sections/hero";
import { HowItWorksSection } from "./_sections/how-it-works";
import { McpSection } from "./_sections/mcp";
import { ProductSection } from "./_sections/product";
import { SiteFooter } from "./_sections/site-footer";
import { WordmarkSection } from "./_sections/wordmark";

/**
 * `/` — the landing page, built 1:1 from the Figma "Card" frame
 * (ZYND-Cohort, node 421:2). Every section is absolutely positioned on the
 * frame's 1440 x 10703 canvas; render order follows the frame's layer order
 * wherever layers overlap.
 */
export default function LandingPage() {
  return (
    <>
      <main className="landing-v2-canvas bg-white h-[10703px] mx-auto overflow-clip relative w-[1440px]">
        <HeroSection />
        <ProductSection />
        <HowItWorksSection />
        <HowItWorksFade />
        <CtaBannerSection />
        <CtaBannerFade />
        <DiscoverSection />
        <McpSection />
        <ExploreSection />
        <FaqSection />
        <WordmarkSection />
      </main>
      <SiteFooter />
    </>
  );
}
