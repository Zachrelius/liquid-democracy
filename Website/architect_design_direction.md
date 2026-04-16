# Liquid Democracy Website — Design Direction

This document contains specific, actionable design decisions for the Dev agent. Where a decision is made, it is final — implement it as described. Where options are noted, the first option is preferred.

---

## 1. Color Palette

### Primary Colors

| Role | Hex | Usage |
|------|-----|-------|
| **Deep Navy** | `#1B2A4A` | Primary backgrounds, headings, footer |
| **White** | `#FFFFFF` | Page backgrounds, text on dark |
| **Off-White** | `#F7F5F2` | Alternate section backgrounds (warm, not cold gray) |

### Accent Color: Warm Amber/Gold

| Role | Hex | Usage |
|------|-----|-------|
| **Amber** | `#D4922A` | Primary accent — CTAs, links on hover, highlights, key stats |
| **Amber Light** | `#F0D9A8` | Subtle backgrounds for callout boxes, hover states on cards |
| **Amber Dark** | `#A67118` | Hover/active state for amber buttons |

**Why amber/gold:** It avoids any partisan association (no red, no blue). Gold conveys civic authority and seriousness — think of it as the color of parchment, seals, and public institutions. It pairs naturally with deep navy without looking corporate. Teal felt too "tech startup." Green felt too "environmental org." Amber is distinctive and grounded.

### Text Colors

| Role | Hex | Usage |
|------|-----|-------|
| **Heading Text** | `#1B2A4A` | All headings (same as navy primary) |
| **Body Text** | `#3A3A3A` | Paragraphs, descriptions |
| **Secondary Text** | `#6B7280` | Captions, meta text, timestamps |
| **Text on Dark** | `#F7F5F2` | Body text on navy backgrounds |

### Semantic Colors

| Role | Hex | Usage |
|------|-----|-------|
| **Success** | `#2D8A56` | Confirmation states, positive indicators |
| **Warning** | `#D4922A` | Reuses amber — alerts, notices |
| **Error** | `#C23B3B` | Form validation, error states |
| **Info** | `#3B82C2` | Informational callouts (use sparingly — it's close to "blue") |

### Contrast Notes
- `#1B2A4A` on `#FFFFFF` = ratio ~12.5:1 (passes AAA)
- `#3A3A3A` on `#FFFFFF` = ratio ~10:1 (passes AAA)
- `#FFFFFF` on `#1B2A4A` = ratio ~12.5:1 (passes AAA)
- `#D4922A` on `#FFFFFF` = ratio ~3.8:1 — **do not use amber for text on white**. Use amber for buttons, borders, icons, and decorative elements only. For links, use navy with amber underline or amber on navy backgrounds.
- `#D4922A` on `#1B2A4A` = ratio ~3.3:1 — suitable for large text and icons only, not small body text.

---

## 2. Typography

### Font Selections (Google Fonts)

**Headlines:** `"Lora"` — a well-designed contemporary serif. It reads as authoritative and literary without feeling stodgy. Weight 600 (semi-bold) for headings, 700 (bold) for the hero headline.

**Body:** `"Inter"` — a highly legible sans-serif designed for screens. Clean, neutral, does not call attention to itself. Weight 400 (regular) for body, 500 (medium) for emphasis, 600 (semi-bold) for bold text.

### Type Scale

| Element | Font | Size (desktop) | Size (mobile) | Weight | Line Height |
|---------|------|----------------|---------------|--------|-------------|
| **Hero Headline** | Lora | 56px / 3.5rem | 36px / 2.25rem | 700 | 1.15 |
| **H1** | Lora | 48px / 3rem | 32px / 2rem | 600 | 1.2 |
| **H2** (section headings) | Lora | 36px / 2.25rem | 28px / 1.75rem | 600 | 1.25 |
| **H3** (subsection) | Lora | 28px / 1.75rem | 22px / 1.375rem | 600 | 1.3 |
| **H4** | Inter | 22px / 1.375rem | 18px / 1.125rem | 600 | 1.35 |
| **H5** | Inter | 18px / 1.125rem | 16px / 1rem | 600 | 1.4 |
| **H6** | Inter | 16px / 1rem | 14px / 0.875rem | 600 | 1.4 |
| **Body** | Inter | 18px / 1.125rem | 16px / 1rem | 400 | 1.7 |
| **Body Large** | Inter | 20px / 1.25rem | 18px / 1.125rem | 400 | 1.65 |
| **Small** | Inter | 14px / 0.875rem | 13px / 0.8125rem | 400 | 1.5 |
| **Caption** | Inter | 12px / 0.75rem | 12px / 0.75rem | 400 | 1.5 |

### Paragraph Settings
- Max paragraph width: `680px` (for readability)
- Letter spacing on body text: `0` (Inter handles this well by default)
- Letter spacing on Lora headings: `-0.01em` (very slight tightening)

---

## 3. Layout Direction Per Section

### Hero Section
- Full-viewport height on desktop (100vh), auto on mobile
- Content centered both vertically and horizontally
- Headline, subheadline, and CTA stacked vertically, center-aligned
- Max content width: `720px`
- Background: deep navy (`#1B2A4A`)
- Text: off-white (`#F7F5F2`)
- CTA button: amber on navy (see button specs below)
- Below the text, leave space for a future animated delegation graph visualization. For now, use a subtle decorative element — a network/node pattern rendered in SVG with low opacity (`0.08`) as a background texture on the hero section. Nodes and connecting lines in off-white.
- A small scroll indicator (thin downward chevron or arrow) at the bottom of the hero, gently pulsing

### "The Problem" Section
- Background: white (`#FFFFFF`)
- Layout: single column, centered, max-width `900px`
- Section heading centered at top
- Statistics displayed as a **vertical stack of statement blocks**, each with:
  - The bold number/statistic on its own line (rendered large: `36px` Lora on desktop)
  - The explanatory sentence below in body text
  - A thin amber left border (`3px`) on each block for visual rhythm
- Transition line at the bottom: styled as a slightly larger, italicized paragraph, centered, with more top margin to set it apart
- Generous vertical spacing between each stat block (`48px`)

### "How Liquid Democracy Works" Section
- Background: off-white (`#F7F5F2`)
- Section heading and intro centered, max-width `720px`
- The five steps displayed as a **numbered vertical sequence**:
  - Each step is a block with: step number (large, amber-colored, Lora font), heading (H3), and 1-2 paragraphs of body text
  - Steps are left-aligned within a centered column (max-width `720px`)
  - A thin vertical line (1px, `#D4922A` at 30% opacity) runs down the left side connecting the step numbers — a subtle "thread" visual
  - Step numbers: `48px`, Lora, amber color, positioned to the left of the content
- Closing line at the bottom: centered, set in Body Large, with `32px` top margin
- On mobile: step numbers sit above the heading (stacked), vertical line hidden

### "Real Precedents" Section
- Background: white (`#FFFFFF`)
- Section heading and intro centered
- **2x2 card grid** on desktop, **single column stack** on mobile
- Each card:
  - Country name as H3
  - Body text paragraph
  - Subtle border (`1px solid #E5E1DB`) with `24px` padding
  - No background color (white on white, border defines the card)
  - On hover: border color shifts to amber, slight shadow (`0 2px 12px rgba(27,42,74,0.08)`)
- "Learn more" link below the grid, centered, styled as a text link with arrow

### "The Platform" Section
- Background: deep navy (`#1B2A4A`)
- Text: off-white
- Section heading centered
- Intro paragraph centered, max-width `720px`
- **Feature grid: 2x2** on desktop, single column on mobile
  - Each feature is a card-like block with:
    - Feature name as H4 (off-white)
    - Description in body text (off-white, slightly reduced opacity: `0.85`)
    - A simple line icon above the heading (amber colored, 32px). Use a minimal icon set — a node/arrow for delegation, an eye for transparency, a group icon for councils, a shield for security.
  - Cards have a subtle border (`1px solid rgba(255,255,255,0.12)`)
- Open source statement below the grid: centered, Body Large, with the quoted portion in amber
- GitHub CTA button centered below

### "Get Involved" Section
- Background: off-white (`#F7F5F2`)
- Section heading centered
- **Three-column layout** on desktop (advocates / developers / organizations), stacked on mobile
- Each column:
  - H3 heading
  - Body paragraph
  - CTA button (see button styles — secondary style for all three)
- Equal width columns with `32px` gap

### Footer
- Background: deep navy (`#1B2A4A`), slightly darker than hero if possible (or same)
- Tagline centered, Lora italic, off-white, `20px`
- Links in a single horizontal row on desktop, two-column grid on mobile
- Link color: off-white, hover: amber
- Bottom line (no-tracking statement): small text, secondary text color on dark (`rgba(255,255,255,0.5)`)
- Adequate padding: `64px` top and bottom

---

## 4. Spacing System

**Base unit:** `8px`

| Token | Value | Usage |
|-------|-------|-------|
| `space-xs` | 4px (0.5x) | Tight gaps, icon padding |
| `space-sm` | 8px (1x) | Inline spacing, small gaps |
| `space-md` | 16px (2x) | Default gap between related elements |
| `space-lg` | 24px (3x) | Gap between card elements, paragraph spacing |
| `space-xl` | 32px (4x) | Gap between subsections, column gaps |
| `space-2xl` | 48px (6x) | Gap between major content blocks within a section |
| `space-3xl` | 64px (8x) | Section padding (top/bottom) on mobile |
| `space-4xl` | 96px (12x) | Section padding (top/bottom) on desktop |
| `space-5xl` | 128px (16x) | Large hero padding |

### Container Widths
- Max content width: `1200px`
- Narrow content (text-heavy): `720px`
- Medium content (cards, grids): `960px`
- Side padding on mobile: `24px`
- Side padding on desktop: `48px` (within the max-width container)

---

## 5. Component Patterns

### Buttons

**Primary Button (amber on dark backgrounds):**
- Background: `#D4922A`
- Text: `#1B2A4A` (navy), Inter 600, `16px`
- Padding: `14px 32px`
- Border-radius: `6px`
- Hover: background `#A67118`, slight lift (`translateY(-1px)`, shadow `0 4px 12px rgba(0,0,0,0.15)`)
- Active: `translateY(0)`, shadow removed
- Transition: `all 0.2s ease`

**Primary Button (amber on light backgrounds):**
- Background: `#D4922A`
- Text: `#FFFFFF`
- Otherwise same as above

**Secondary Button:**
- Background: transparent
- Border: `2px solid #1B2A4A`
- Text: `#1B2A4A`, Inter 600, `16px`
- Padding: `12px 30px` (adjust for border)
- Border-radius: `6px`
- Hover: background `#1B2A4A`, text `#FFFFFF`
- Transition: `all 0.2s ease`

**Secondary Button (on dark backgrounds):**
- Border: `2px solid #F7F5F2`
- Text: `#F7F5F2`
- Hover: background `#F7F5F2`, text `#1B2A4A`

**Text Link:**
- Color: `#1B2A4A` on light backgrounds, `#F7F5F2` on dark
- Underline: `2px solid #D4922A`, offset `3px`
- Hover: underline color darkens to `#A67118`

### Cards
- Background: white or transparent (defined per section above)
- Border: `1px solid #E5E1DB`
- Border-radius: `8px`
- Padding: `24px`
- Hover: border-color transitions to `#D4922A`, box-shadow `0 2px 12px rgba(27,42,74,0.08)`
- Transition: `all 0.25s ease`

### Section Separators
- No visible horizontal rules between sections. Sections are separated by alternating background colors (white / off-white / navy). This creates natural visual breaks without clutter.

### Stat Block (Problem Section)
- Left border: `3px solid #D4922A`
- Padding-left: `24px`
- Number/stat: Lora, `36px`, `#1B2A4A`, weight 700
- Description: Inter, `18px`, `#3A3A3A`, weight 400

---

## 6. Responsive Approach

### Breakpoints

| Name | Width | Notes |
|------|-------|-------|
| **Mobile** | < 640px | Single column everywhere, reduced type scale, hamburger nav |
| **Tablet** | 640px – 1023px | Two-column grids become single or two column depending on content |
| **Desktop** | >= 1024px | Full layout as described |
| **Large Desktop** | >= 1440px | Content stays max-width, generous side margins |

### Key Responsive Behaviors
- **Navigation:** Horizontal link row on desktop. Hamburger menu on mobile (slide-in from right, full-height overlay with navy background).
- **Hero:** Text size reduces per type scale. Hero may not be full viewport on mobile — let it be natural height with generous padding.
- **Problem section stats:** Stack naturally (they're already single-column).
- **How It Works steps:** Vertical line and side-positioned numbers disappear on mobile. Numbers stack above headings.
- **Precedents grid:** 2x2 on desktop, 2x1 on tablet, 1x1 on mobile.
- **Platform features grid:** 2x2 on desktop, 1x1 on mobile.
- **Get Involved columns:** Three columns on desktop, stacked on mobile with `32px` vertical gap.
- **Footer links:** Horizontal row on desktop, two-column grid on mobile.

### Mobile-Specific Adjustments
- Section padding reduces from `96px` to `64px` top/bottom
- Card padding reduces from `24px` to `16px`
- Button width: `100%` on mobile within content column (not full screen)

---

## 7. Animation / Interaction Notes

### Scroll Animations (use IntersectionObserver or CSS-only where possible)
- **Fade-up on enter:** Each major content block (stat blocks, step blocks, cards) should fade in and translate up slightly (`20px`) when entering the viewport. Stagger children by `100ms` in grid layouts.
- **Duration:** `0.6s` with `ease-out` timing
- **Trigger:** When element is ~20% visible
- **Respect reduced motion:** Wrap all animations in `@media (prefers-reduced-motion: no-preference)`. If user prefers reduced motion, everything appears immediately with no animation.

### Specific Animations
- **Hero scroll indicator:** Gentle pulse animation (opacity `0.4` to `1`, `2s` loop, ease-in-out)
- **How It Works vertical line:** Draws from top to bottom as user scrolls through the section (optional — only implement if it can be done without heavy JS libraries). Fallback: just show the line statically.
- **Stat numbers (Problem section):** Count-up animation when they scroll into view (e.g., "91%" counts from 0 to 91). Keep it quick (`1.2s`). Fallback: just show the number.

### Hover States
- Buttons: as described in component section (lift + shadow)
- Cards: border color + shadow transition
- Text links: underline color shift
- Navigation links: amber underline slides in from left (`transform: scaleX(0)` to `scaleX(1)`)

### Performance Constraints
- No animation libraries (no GSAP, Framer Motion, etc.) — CSS transitions and IntersectionObserver only
- No parallax scrolling
- No video backgrounds
- No particle effects
- Total JS for animations should be under 5KB

---

## 8. What to Avoid

These are firm "don'ts" for the entire site:

1. **No American flag imagery or red/white/blue color schemes.** This is not a patriotic site. It's a civic technology project that should feel international.
2. **No stock photography.** No photos of diverse people shaking hands, no politicians at podiums, no "hero images" of crowds. Use illustrations, icons, and data visualizations instead.
3. **No Silicon Valley language.** Never use: "disrupt," "scale," "10x," "leverage," "synergy," "game-changing," "revolutionary." The copy already avoids this — the design should too (no gradient meshes, no glassmorphism, no trendy startup aesthetics).
4. **No aggressive engagement patterns.** No popups, no modals on page load, no "subscribe before you leave" overlays, no email gates, no countdown timers, no urgency language in the UI.
5. **No tracking.** No Google Analytics, no Facebook Pixel, no cookies beyond what's technically necessary. If any analytics are added later, they must be privacy-respecting (e.g., Plausible, self-hosted).
6. **No heavy frameworks for a content site.** If using a framework, it must produce mostly static HTML. No client-side rendering of text content. No loading spinners for the main page.
7. **No decorative clutter.** No confetti, no emoji in headings, no gradient text, no floating shapes. The design should feel like a well-typeset document with thoughtful spacing, not a marketing page competing for attention.
8. **No dark patterns.** Pre-checked boxes, hidden unsubscribe mechanisms, misleading button labels — none of it. A democracy site must practice what it preaches.
