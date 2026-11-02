# DESIGN.md - Classy Cream & Editorial Visual Identity

> **CRITICAL INSTRUCTION FOR AI AGENT:** You must read and strictly adhere to this design specification before generating or modifying any markup, CSS, or frontend components. Do not rely on your internal default UI patterns, generic placeholders, or standard templates.

---

## 1. THE ANTI-SLOP & ANTI-VIBE-CODE GUARDRAILS
To prevent the application from looking like a generic, prompt-generated template, you are strictly prohibited from using common AI design elements:

*   **NO Purple/Indigo Gradients:** Absolutely no neon violet, magenta, or indigo cyber-gradients.
*   **NO Glassmorphism & Translucency:** Do not use `backdrop-blur`, semi-transparent frosted glass panels, or glowing ambient backlights.
*   **NO Generic Icon Grids:** Do not build symmetrical 3-column grids filled with generic Lucide icons (`Sparkles`, `Brain`, `Zap`).
*   **NO Bubble / Pill Architecture:** Avoid overly rounded card corners and pill-shaped structural containers. Everything must feel grounded, editorial, and deliberate.

---

## 2. DESIGN SYSTEM TOKENS

### The Editorial Palette
The visual identity relies on a high-end, sophisticated interplay between a warm, rich cream base and a deep, intellectual forest ink accent. Do not introduce any unauthorized accent colors.

*   **Primary Canvas (Cream):** `#FDFBF7` (A warm, rich, elegant cream that prevents screen fatigue).
*   **Secondary Canvas (Soft Linen):** `#F5F2EB` (Slightly deeper cream tone for subtle structural depth and section breaks).
*   **The Complementary Ink (Deep Forest):** `#1A2E26` (A sophisticated, ultra-dark muted forest green with charcoal undertones. Used for typography, structural borders, and high-impact structural elements).
*   **Muted Accents / Rules:** `#DCD7CC` (A balanced, muted beige-grey for thin borders and dividers).

### Typography & Editorial Hierarchy
Typography must mimic a premium print magazine or high-end design house.

*   **Display & Headings:** Use an elegant, high-contrast Serif font stack.
    *   *CSS:* `Playfair Display`, `Cormorant Garamond`, `Georgia`, `serif`.
    *   *Attributes:* Low tracking (`letter-spacing: -0.03em`), deliberate font-weights (`font-weight: 500` or `600`).
*   **Body & System Elements:** Use a crisp, highly legible geometric or grotesque sans-serif.
    *   *CSS:* `Inter`, `Helvetica Neue`, `-apple-system`, `sans-serif`.
    *   *Attributes:* Increased line-height (`leading-relaxed` / `1.6`), generous tracking for small labels (`letter-spacing: 0.05em`).

### Spacing & Layout Structural Rules
*   **Borders:** Use razor-sharp corners or an ultra-minimal radius (`2px` to `4px` maximum).
*   **Dividers:** Prefer thin, elegant hairline borders (`1px solid #DCD7CC`) over artificial drop shadows or background color blocks.
*   **Whitespace:** Prioritize massive, open breathing room. Use asymmetric layouts (e.g., a massive left column with typography balanced by a single, perfectly framed image on the right).

---

## 3. COMPONENT IMPLEMENTATION PATTERNS

### Layout & Sectioning
Instead of boxing everything in cards, separate your ideas utilizing empty space and fine rules.
*   **Hero Sections:** Large, prominent Serif type rendered in **Deep Forest Ink (`#1A2E26`)** set against the clean **Cream (`#FDFBF7`)** canvas.
*   **Interactive Call-to-Actions (Buttons):**
    *   *Primary:* Solid **Deep Forest Ink** block with sharp corners and crisp white/cream text. No gradient. No shadow.
    *   *Secondary:* Transparent background with a thin hairline border in deep forest ink.

### Imagery & Graphic Treatment
*   **No Abstract Vector Elements:** Replace floating geometric shapes or blurred meshes with high-fidelity, desaturated photography, architectural lines, or clean, dense data layouts.
*   **Aspect Ratios:** Use structural, rigid aspect ratios for media blocks (e.g., standard `4:3` or wide `16:9` frames with solid 1px borders).

---

## 4. ARCHITECTURAL CHANGELOG
*The AI Agent must document every visual change here to ensure aesthetic alignment over time.*

*   **Log Entry Template:** `[Date] - [Component] - Refinement detail bypassing AI default.`
*   `2026-11-03 - Global background - Removed animated aurora mesh, blurred gradient orbs and noise grain; flat Cream (#FDFBF7) canvas with Linen (#F5F2EB) section breaks. Also the main rendering-cost fix.`
*   `2026-11-03 - Tokens - Replaced the 7-colour neon palette and dark theme with the four editorial tokens; secondary text uses ink tints (#4A5D55, #7D8A83) only. Removed the theme toggle.`
*   `2026-11-03 - Typography - Playfair Display for display, headings, metric figures and empty states; Inter for body; JetBrains Mono for tabular numbers and tickers. Italic serif used for emphasis instead of gradient text.`
*   `2026-11-03 - Navigation Bar - Flat Cream bar with a 1px Deep Forest baseline rule; eliminated floating pill navigation and the blur-on-scroll panel.`
*   `2026-11-03 - Hero - Asymmetric 7/5 grid: oversized serif headline left; a single 4:3 bordered "Fig. 1" frame on the right holding the live efficient frontier with a magazine-style caption. Removed floating metric chips, 3D tilt and parallax.`
*   `2026-11-03 - Feature section - Replaced the icon bento grid with a numbered two-column contents list (01–06) separated by hairline rules.`
*   `2026-11-03 - Research section - Figures set in a ruled row with vertical hairlines; chart in a 16:7 bordered "Fig. 2" frame with caption. Removed counting animations.`
*   `2026-11-03 - Method section - Six-step process rendered as a ruled editorial table rather than step cards.`
*   `2026-11-03 - Buttons - Solid ink primary and hairline-outline secondary, 2px radius, no gradient, no shadow, no spring animation.`
*   `2026-11-03 - App panels - Cards are no longer boxed: each panel opens with a 1px ink top rule and a serif heading; controls sit in a single Linen panel with a hairline border.`
*   `2026-11-03 - Metrics - Ruled row of serif figures divided by vertical hairlines instead of glowing tinted tiles; figures are set statically, not counted up.`
*   `2026-11-03 - Sidebar - Numbered text navigation (01–08) with an underline for the current page; removed icons and the sliding glow indicator.`
*   `2026-11-03 - Controls - Segmented choices as a ruled grid, square checkboxes, square slider thumbs on a hairline track, square chips.`
*   `2026-11-03 - Provenance labels - Source tags (Historical / Backtest / Ex-ante / Simulated / Saved experiment) as small caps with a 1px ink left rule instead of coloured pills.`
*   `2026-11-03 - Charts - Single-ink chart system: highlighted series in solid forest ink, others in a tonal ink/beige scale distinguished by dash pattern; cream-to-ink heatmaps; hollow ink markers; tail bars in ink against beige; no draw-in animation.`
*   `2026-11-03 - Feedback - Toasts as flat ink bars; loading as a hairline progress rule; tooltips as ink blocks.`
*   `2026-11-03 - Forms - "Out-of-sample from" date field (Optimise and Backtesting), same ruled input style as the start/end dates; provenance line adds "optimised on <start> → <end>".`
*   `2026-11-03 - Charts - Log axes label a 1-2-5 grid, falling back to finer steps (e.g. 80k/100k/120k) on short ranges; hovering a series on the price chart fades the others.`
