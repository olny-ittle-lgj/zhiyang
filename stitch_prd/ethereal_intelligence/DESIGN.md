---
name: Ethereal Intelligence
colors:
  surface: '#111316'
  surface-dim: '#111316'
  surface-bright: '#37393d'
  surface-container-lowest: '#0c0e11'
  surface-container-low: '#1a1c1f'
  surface-container: '#1e2023'
  surface-container-high: '#282a2d'
  surface-container-highest: '#333538'
  on-surface: '#e2e2e6'
  on-surface-variant: '#c0c7d4'
  inverse-surface: '#e2e2e6'
  inverse-on-surface: '#2f3034'
  outline: '#8a919e'
  outline-variant: '#404752'
  surface-tint: '#a2c9ff'
  primary: '#a2c9ff'
  on-primary: '#00315b'
  primary-container: '#409eff'
  on-primary-container: '#003460'
  inverse-primary: '#0060a9'
  secondary: '#e6feff'
  on-secondary: '#003739'
  secondary-container: '#00f4fe'
  on-secondary-container: '#006c71'
  tertiary: '#7cd8b1'
  on-tertiary: '#003827'
  tertiary-container: '#50ac88'
  on-tertiary-container: '#003b29'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#d3e4ff'
  primary-fixed-dim: '#a2c9ff'
  on-primary-fixed: '#001c38'
  on-primary-fixed-variant: '#004881'
  secondary-fixed: '#63f7ff'
  secondary-fixed-dim: '#00dce5'
  on-secondary-fixed: '#002021'
  on-secondary-fixed-variant: '#004f53'
  tertiary-fixed: '#98f5cc'
  tertiary-fixed-dim: '#7cd8b1'
  on-tertiary-fixed: '#002115'
  on-tertiary-fixed-variant: '#00513a'
  background: '#111316'
  on-background: '#e2e2e6'
  surface-variant: '#333538'
  deep-charcoal: '#0B0C0E'
  slate-gray: '#2C313A'
  electric-blue: '#00F5FF'
  mint-evolution: '#A2FFD6'
  error-red: '#F56C6C'
  warning-amber: '#E6A23C'
typography:
  headline-lg:
    fontFamily: Inter
    fontSize: 40px
    fontWeight: '700'
    lineHeight: 48px
    letterSpacing: -0.02em
  headline-lg-mobile:
    fontFamily: Inter
    fontSize: 30px
    fontWeight: '700'
    lineHeight: 36px
  headline-md:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  label-md:
    fontFamily: JetBrains Mono
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
    letterSpacing: 0.05em
  label-sm:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 8px
  container-max: 1440px
  gutter: 24px
  margin-sm: 16px
  margin-md: 32px
  margin-lg: 64px
---

## Brand & Style

The design system embodies a **Minimalist Tech** aesthetic tailored for an AI-driven knowledge workshop. It balances the intellectual rigor of a systematic "workshop" with the fluid, evolving nature of artificial intelligence. The personality is sophisticated, transparent, and forward-thinking.

The visual style is defined by **Glassmorphism** and **Minimalism**. It uses translucent layers, backdrop blurs, and vibrant electric accents to signify "living" data. The interface prioritizes clarity and focus, using generous whitespace to prevent information overload during complex AI reasoning processes. The experience should feel like stepping into a high-end, digital laboratory where knowledge is nurtured and refined.

## Colors

The palette is optimized for a dark-mode-first environment. The foundation is built on **Deep Charcoal** and **Slate Grays**, providing a low-fatigue backdrop for technical work. 

- **Primary Action**: A deep, reliable blue used for global navigation and core CTAs.
- **AI/Tech Accents**: A vibrant **Electric Blue** used sparingly for AI "thinking" states, glowing borders, and data nodes.
- **Success/Evolution**: A **Soft Mint Green** representing growth, completion, and positive "Evolution" outcomes.
- **Functional States**: Standard semantic colors (Amber and Red) are utilized for warnings and errors but are desaturated slightly to fit the tech-centric aesthetic.

## Typography

This design system uses **Inter** for all primary communication to ensure maximum readability across AI-generated text and complex summaries. It provides a neutral yet modern tone that supports the minimalist aesthetic.

For technical metadata, system logs, and "Thinking Card" details, **JetBrains Mono** is employed. This monospaced font reinforces the "workshop" feel and distinguishes AI-generated logic or IDs from human-readable content. All headlines use tighter letter spacing for a premium, editorial look.

## Layout & Spacing

The layout follows a **Fluid Grid** model with a maximum container width of 1440px for desktop. It utilizes a base 8px rhythm to ensure consistent alignment.

- **Desktop**: 12-column grid with 24px gutters. Use generous side margins (64px) for the knowledge portal to create a focused, "zen" reading environment.
- **Tablet**: 8-column grid with 16px gutters and margins.
- **Mobile**: 4-column grid with 16px margins. 

Layouts in the "Evolution Center" should utilize side-by-side (parallel) comparison panels, allowing users to track original vs. AI-suggested changes with clear vertical alignment.

## Elevation & Depth

Depth is achieved through **Glassmorphism** and **Tonal Layering** rather than traditional heavy shadows.

- **Surface Level 0**: Background (#0B0C0E).
- **Surface Level 1**: Secondary containers using subtle fills of Slate Gray.
- **Surface Level 2 (Glass)**: Elevated "Thinking Cards" and Modals. These use a semi-transparent background (approx. 60% opacity) with a `20px` backdrop blur and a `1px` low-opacity white border.
- **AI Glow**: Critical AI components or active "Evolution" cards feature a subtle `0 0 15px` outer glow in Electric Blue to signal activity and focus.

## Shapes

The shape language is **Rounded** and modern. 

- **Cards and Containers**: Use a base 0.5rem (8px) radius. Larger cards or modals use 1rem (16px) to appear more approachable.
- **Pills**: Use a full-pill radius for status tags, badges, and the "Interval Repetition" indicators.
- **Dividers**: Should be extremely thin (1px) and use low-contrast slate colors to maintain the minimalist feel.

## Components

### Evolutionary Thinking Cards
The cornerstone component. Use glassmorphic backgrounds with a vertical timeline on the left. AI "Internal Monologue" text is set in `label-md` (JetBrains Mono). Cards are collapsible to manage high information density.

### Progress Trackers
Linear, thin-line trackers. Use **Electric Blue** for active progress and **Mint Green** for completion. Success states should include a subtle "pulse" animation.

### Multi-source Uploaders
A minimalist drop-zone with a `dashed` slate border. Upon file selection, it transforms into a list of progress bars using the glassmorphic style.

### Game-Mode Selectors
Large, card-based buttons with high-contrast icons. Use **Electric Blue** glow on hover. Each game (Monopoly, Match Match) features a unique theme-colored border glow.

### Buttons & Inputs
- **Primary Button**: Solid Electric Blue with white text, 8px radius.
- **Secondary/Ghost Button**: Thin 1px white border with no fill, glowing on hover.
- **Inputs**: Dark background (#121417) with a 1px slate border that turns Electric Blue when focused.

### Icons
Use **Sleek, thin-line icons** (1.5px stroke). Icons for AI actions should be distinguished by an Electric Blue tint.