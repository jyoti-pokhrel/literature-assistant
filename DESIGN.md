---
name: Research Agent
description: AI-assisted literature review and research gap detection platform
colors:
  surface-bg: "#f5f7fa"
  surface-2: "#eceff5"
  ink-primary: "#050608"
  ink-secondary: "#4a5564"
  ink-tertiary: "#8b95a4"
  accent: "#050608"
  glass: "rgba(255, 255, 255, 0.55)"
  glass-2: "rgba(255, 255, 255, 0.72)"
  glass-strong: "rgba(255, 255, 255, 0.85)"
typography:
  display:
    fontFamily: "'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Helvetica, sans-serif"
    fontSize: "clamp(2.4rem, 5.4vw, 4.25rem)"
    fontWeight: 300
    lineHeight: 1.1
  headline:
    fontFamily: "'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Helvetica, sans-serif"
    fontSize: "clamp(1.625rem, 2.8vw, 2.25rem)"
    fontWeight: 600
    lineHeight: 1.2
  title:
    fontFamily: "'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Helvetica, sans-serif"
    fontSize: "clamp(1.15rem, 1.8vw, 1.4rem)"
    fontWeight: 600
    lineHeight: 1.3
  body:
    fontFamily: "'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Helvetica, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Helvetica, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 500
    lineHeight: 1.4
  mono:
    fontFamily: "ui-monospace, 'SF Mono', SFMono-Regular, Menlo, Monaco, monospace"
    fontSize: "0.72rem"
    fontWeight: 400
    lineHeight: 1.4
rounded:
  sm: "10px"
  md: "14px"
  lg: "20px"
  xl: "28px"
  pill: "999px"
spacing:
  0: "0.25rem"
  1: "0.5rem"
  2: "1rem"
  3: "1.5rem"
  4: "2rem"
  5: "3rem"
  6: "4rem"
  7: "6rem"
  8: "8rem"
components:
  button-primary:
    backgroundColor: "{colors.ink-primary}"
    textColor: "#ffffff"
    rounded: "{rounded.lg}"
    padding: "12px 24px"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.ink-primary}"
    rounded: "{rounded.lg}"
    padding: "12px 24px"
  input:
    backgroundColor: "{colors.glass-2}"
    textColor: "{colors.ink-primary}"
    rounded: "{rounded.md}"
    padding: "12px 16px"
  card:
    backgroundColor: "{colors.glass}"
    rounded: "{rounded.lg}"
    padding: "24px"
---

# Design System: Research Agent

## 1. Overview

**Creative North Star: "The Research Workbench"**

A precision instrument for academic researchers. The interface treats data as the protagonist—papers, clusters, gaps, and synthesis reports displayed through subtle glassmorphism panels that recede to let content breathe. The aesthetic is Apple-clean: refined, trustworthy, unadorned. Nothing decorative; everything functional. The frosted glass panels create hierarchy without weight, like sheets of paper organized on a clean desk.

This system explicitly rejects: generic SaaS landing page aesthetics, overly dense academic software interfaces, and flashy consumer-app styling. The target user is a researcher who values efficiency and clarity over novelty.

**Key Characteristics:**
- Monochrome palette with subtle warm undertones (Ink on Paper)
- Frosted glass panels for structural hierarchy
- Generous whitespace; content never feels cramped
- Plus Jakarta Sans for a modern, professional, yet approachable feel
- Light/dark theme support via CSS custom properties

## 2. Colors

The palette is deliberately restrained—monochrome with a single voice. No saturated accents; the "accent" is pure ink at various opacities. This restraint puts focus on the research content.

### Primary (Ink)
- **Deep Ink** (#050608): Primary text, buttons, active states. The anchor of the entire system.
- **Soft Ink** (#4a5564): Secondary text, icons, supporting elements.

### Neutral
- **Paper White** (#f5f7fa): Main background—near-white with the faintest cool tint.
- **Soft Grey** (#eceff5): Secondary backgrounds, nested surfaces.
- **Muted Grey** (#8b95a4): Tertiary text, disabled states, dividers.

### Glass (Structural)
- **Light Glass** (rgba(255, 255, 255, 0.55)): Primary glass panels.
- **Medium Glass** (rgba(255, 255, 255, 0.72)): Cards, elevated surfaces.
- **Strong Glass** (rgba(255, 255, 255, 0.85)): Input fields, high-contrast surfaces.

**The Ink Rule.** The primary accent is ink itself—near-black at full opacity. There is no secondary accent color. The system's voice comes from opacity variations and glass treatment, not hue.

## 3. Typography

**Primary Font:** Plus Jakarta Sans (with Apple system fallbacks)
**Monospace:** SF Mono / ui-monospace

**Character:** Professional yet approachable. Not cold like a terminal, not playful like a consumer app. The geometric yet humanist qualities of Plus Jakarta Sans convey competence without intimidation—appropriate for academic researchers who need to trust their tool.

### Hierarchy
- **Display** (clamp(2.4rem, 5.4vw, 4.25rem), weight 300): Hero headlines, synthesis report titles.
- **Headline** (clamp(1.625rem, 2.8vw, 2.25rem), weight 600): Page titles, major section headers.
- **Title** (clamp(1.15rem, 1.8vw, 1.4rem), weight 600): Card titles, component headers.
- **Body** (1rem, weight 400): Primary content, descriptions. Max line length capped at 65–75ch for readability.
- **Label** (0.875rem, weight 500): Button labels, form labels, navigation.
- **Mono** (0.72rem): Code snippets, citations, technical data.

**The Hierarchy Rule.** Use weight contrast (400 vs 600) alongside size contrast. Never use a single weight across all levels—differentiation is the point.

## 4. Elevation

This system uses **layered glass**—frosted glass panels at varying opacities create depth without heavy shadows. The glassmorphism is purposeful, not decorative: it distinguishes structural layers (navigation, content, overlays) without competing with data content.

### Shadow Vocabulary
- **Subtle** (`0 1px 2px rgba(5, 6, 8, 0.04), 0 8px 24px rgba(5, 6, 8, 0.06)`): Default card elevation, hover states.
- **Strong** (`0 1px 2px rgba(5, 6, 8, 0.04), 0 24px 60px rgba(5, 6, 8, 0.10)`): Modal backgrounds, significant elevation.
- **Glass** (inset highlights + ambient shadow): Frosted glass panels with subtle inner glow.

**The Glass-by-Default Rule.** Glass panels are the primary structural element, not decoration. They define hierarchy: content floats beneath glass navigation, glass cards hold paper metadata, glass overlays contain modals.

**The Flat-at-Rest Rule.** Elements are flat when idle. Glass treatment and shadows appear to distinguish layers, not as ambient decoration.

## 5. Components

### Buttons
- **Shape:** Generous radius (20px / --radius-lg)—Apple-coded, soft but not pill-shaped.
- **Primary:** Ink background (#050608), white text. Padding: 12px 24px.
- **Secondary:** Transparent background, ink text. Border: 1px solid rgba(5, 6, 8, 0.14).
- **Hover:** Subtle background shift (rgba(5, 6, 8, 0.06)). Transition: 180ms ease-out.
- **Focus:** Clear focus ring for keyboard navigation.

### Cards (Glass Panels)
- **Corner Style:** 20px radius (--radius-lg)
- **Background:** var(--glass) for surface cards, var(--glass-2) for content cards
- **Shadow:** Reference elevation—subtle at rest, stronger on hover
- **Border:** 1px solid rgba(255, 255, 255, 0.72) for glass definition
- **Internal Padding:** 24px (--s-4)

### Inputs / Fields
- **Style:** var(--glass-2) background, 14px radius, 1px border (rgba(5, 6, 8, 0.14))
- **Focus:** Border shifts to ink at full opacity, subtle glow
- **Padding:** 12px 16px
- **Placeholder:** ink-tertiary color

### Navigation
- **Style:** Glass background (rgba(245, 247, 250, 0.66) light / rgba(7, 9, 14, 0.66) dark)
- **Typography:** Label weight (0.875rem, weight 500)
- **States:** Default (ink-secondary), hover (ink-primary), active (ink-primary with underline or background)

### The D3 Cluster Map (Signature Component)
- **Canvas:** Full-width, responsive container for the interactive literature map
- **Nodes:** Circle markers sized by paper citation count, colored by cluster
- **Edges:** Subtle lines showing citation relationships
- **Hulls:** Topographical hulls around thematic clusters with glass-tinted fill

## 6. Do's and Don'ts

### Do:
- **Do** use the glass hierarchy to distinguish structural layers (nav, content, overlays)
- **Do** cap body text at 65–75ch for optimal reading comfort
- **Do** use weight contrast (400 vs 600) alongside size for type hierarchy
- **Do** respect `prefers-reduced-motion`—disable the mesh drift animation
- **Do** keep the palette monochrome; let data provide the color (cluster colors in visualizations)

### Don't:
- **Don't** use saturated accent colors—the system is deliberately restrained
- **Don't** add glassmorphism to content elements (it distracts from data)
- **Don't** use border-left or border-right as colored stripes (the side-stripe ban)
- **Don't** use gradient text for emphasis (the gradient text ban)
- **Don't** create identical card grids—vary spacing and content density intentionally
- **Don't** reach for modals first—use inline expansion or progressive disclosure
- **Don't** mimic generic SaaS aesthetics—avoid the cookie-cutter landing page look