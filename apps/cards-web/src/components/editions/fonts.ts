import { Plus_Jakarta_Sans, Space_Mono } from "next/font/google";

// The same faces the public card uses, loaded here too so the editor, the
// create flow and the QR screen draw the edition identically.
const ui = Plus_Jakarta_Sans({ subsets: ["latin"], weight: ["500", "600", "700", "800"], variable: "--ed-ui", display: "swap" });
const mono = Space_Mono({ subsets: ["latin"], weight: ["400", "700"], variable: "--ed-mono", display: "swap" });

/** Put on the root of anything drawn in an edition look. */
export const EDITION_FONT_VARS = `${ui.variable} ${mono.variable}`;
