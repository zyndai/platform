import { Bricolage_Grotesque, Fraunces, Pixelify_Sans } from "next/font/google";

const display = Fraunces({ subsets: ["latin"], weight: ["600", "700"], variable: "--ed-display", display: "swap" });
const ui = Bricolage_Grotesque({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--ed-ui", display: "swap" });
const pixel = Pixelify_Sans({ subsets: ["latin"], weight: ["500"], variable: "--ed-pixel", display: "swap" });

/** Put on the root of anything drawn in an edition look. */
export const EDITION_FONT_VARS = `${display.variable} ${ui.variable} ${pixel.variable}`;
