---
description: OpenWolf's design brain — pick/migrate UI frameworks or audit/fix UI against the anti-generic design principles
argument-hint: [migrate [framework] | audit [target] | fix [target]]
---

Arguments: $ARGUMENTS

Read the **Knowledge base** at the end of this file first — it contains the **Design Principles
(anti-generic mandate)**, the framework knowledge base, and the migration prompts.
Use `.wolf/anatomy.md` to locate UI files instead of scanning.

Pick the mode from the arguments (default: `migrate` if a framework is named or the
user is choosing one; otherwise ask which mode they want):

## Mode: migrate [framework]
Framework selection and migration.
1. If no framework is named, ask the Decision Questions from the Knowledge base
   (stop early once the answer narrows to 1–2 options) and recommend one.
2. Use that framework's prompt from the Knowledge base, adapted to this project's
   real structure via `.wolf/anatomy.md`.
3. The Design Principles override anything generic in the prompt: no template
   hero→features→CTA structures, no stock palettes — distinctive by default.

## Mode: audit [target]
Walk the target (default: the whole UI) and flag every match against the AI-tell
blocklist in the Design Principles: purple gradient heroes, glassmorphism-everything,
emoji headings, generic 3-column feature grids, stock Tailwind palette, Inter for
every role, template SaaS structure, filler microcopy. Produce a findings table —
component, tell matched, severity, specific replacement direction — and end with the
3 changes that would most increase distinctiveness.

## Mode: fix [target]
Run the audit, then fix findings in severity order. Fixes must move toward, not merely
away: typography chosen with intent, a palette derived from the product's actual
brand/domain, asymmetry where it serves hierarchy, copy specific to what the product
does, density appropriate to the audience. Preserve the existing framework and
component APIs — this is a design pass, not a rewrite. After each fix, state what
changed and why it reads as designed-on-purpose.

Acceptance criterion for every mode: **if the result could be swapped onto any other
product without anyone noticing, it fails.**

---

# OpenWolf Reframe — UI Framework Knowledge Base

When the user asks to change, pick, migrate, or "reframe" their UI framework, use this file to guide the conversation and generate the right migration prompt.

## Design Principles — the anti-generic mandate (applies to EVERY prompt below)

**Nothing you produce may look AI-generated.** The recognizable AI aesthetic is a
failure state, no matter which framework is chosen. Apply these rules to every
migration, every component, every page:

**Never produce (the AI-tell blocklist):**
- Purple/indigo/violet gradient heroes, or gradient text on centered headlines
- Glassmorphism cards as the default surface; rounded-2xl + soft shadow on everything
- ✨ 🚀 🎉 emoji in headings or feature lists
- Generic 3-column icon–title–blurb feature grids
- Gradient blob / mesh backgrounds and meaningless floating 3D shapes
- The stock Tailwind palette used as-is; Inter (or system font) for every text role
- One uniform 8px spacing rhythm with no density variation anywhere
- The dark-purple SaaS landing template (hero → logo bar → 3 features → CTA)
- Filler copy ("Supercharge your workflow", "Built for developers, by developers")

**Always aim for:**
- Typography chosen with intent: a deliberate pairing, optical sizes, tightened
  tracking on display text — type does the branding work
- A palette derived from the product's actual domain and brand, not the framework's
  default theme
- Asymmetry and grid-breaking where it serves hierarchy; density that matches the
  audience (data tools can be dense; consumer pages can breathe)
- Copy that is specific to what this product does — never template filler
- **Distinctiveness as an acceptance criterion**: if the design could be swapped onto
  any other product without anyone noticing, it fails review

The `/reframe audit` and `/reframe fix` modes check and repair existing UI against
these rules; run them after any migration.

## Decision Questions

Ask these in order. Stop early if the answer narrows to 1-2 frameworks.

1. **What framework/library does your project currently use?** (React, Vue, Svelte, plain HTML, etc.)
2. **What's your priority?** (a) Stunning animations, (b) Fast setup / ship quickly, (c) Full design control, (d) Accessibility-first, (e) Business/enterprise look
3. **Do you use Tailwind CSS already?** (Yes → most options work. No → Chakra UI or DaisyUI are easier without it)
4. **Light mode, dark mode, or both?**
5. **Is this a landing page, a dashboard/app, or both?**

## Quick Selection Guide

| Priority | Recommended |
|----------|-------------|
| Fastest setup | DaisyUI, Preline UI |
| Stunning animations | Aceternity UI, Magic UI |
| Maximum control | shadcn/ui, Headless UI |
| Most free components | Origin UI (400+) |
| Multi-framework (React + Vue + Svelte) | Park UI, DaisyUI, Flowbite |
| AI product aesthetic | Cult UI |
| Polished defaults + accessibility | HeroUI, Chakra UI, Astryx |
| Business/enterprise | Flowbite, shadcn/ui |
| Full design system + theming, agent-friendly docs | Astryx |

## Comparison Matrix

| Framework | Styling | Animation | Setup | Best For | Cost |
|-----------|---------|-----------|-------|----------|------|
| shadcn/ui | Tailwind + Radix | Minimal | Medium | Full apps, dashboards | Free |
| Aceternity UI | Tailwind + Framer Motion | Heavy, cinematic | Easy (copy-paste) | Animated landing pages | Free / Pro |
| Magic UI | Tailwind + Motion | Purposeful, polished | Easy (shadcn CLI) | SaaS marketing | Free / Pro |
| DaisyUI | Tailwind plugin | CSS transitions | Very easy | Rapid prototyping | Free |
| HeroUI | Tailwind + React Aria | Smooth built-in | Easy | React apps, accessible | Free |
| Chakra UI | CSS-in-JS (Emotion) | Built-in transitions | Easy | Themed React apps | Free |
| Flowbite | Tailwind plugin | CSS transitions | Very easy | Multi-framework, business | Free / Pro |
| Preline UI | Tailwind plugin | CSS + minimal JS | Very easy | Speed-focused builds | Free / Pro |
| Park UI | Tailwind + Ark UI | Minimal | Medium | Multi-framework, design systems | Free |
| Origin UI | Tailwind + shadcn | Minimal | Easy (copy-paste) | Max component variety | Free |
| Headless UI | Custom Tailwind | Custom (Transition) | Medium-Hard | Full design control | Free |
| Cult UI | Tailwind + shadcn | Modern, subtle | Medium | AI apps, full-stack | Free |
| Astryx | StyleX-authored; override with anything | Built-in, subtle | Easy (npm, no build plugin) | Design-system apps, agent-assisted teams | Free (MIT) |

---

## Framework Prompts

After the user selects a framework, use the corresponding prompt below. **Adapt it to the user's actual project** — replace generic references with their real file structure, existing routes, and components from `.wolf/anatomy.md`.

**Migration scope — required for every framework below:** When a project already has a UI, its existing routes, screens, content, data flows, and behavior are the migration target. Preserve them while changing the component library; do not replace the app with a landing page or add sections such as pricing, testimonials, FAQs, or social proof unless the user explicitly asks for them. The section lists below are optional examples only for a new page the user specifically requests, never a migration checklist.

**The Design Principles section overrides anything generic in these prompts.** The example sections below are optional references, not required content. During a migration, add no screens or sections absent from the existing app unless the user requests them. For an explicitly requested new page, select only relevant content and arrange it to pass the distinctiveness criterion.

---

### shadcn/ui

**Stack:** React, Tailwind CSS, Radix UI
**Install:** `npx shadcn@latest init`
**Site:** ui.shadcn.com

```
Migrate the existing UI to shadcn/ui, preserving its framework, routes, screens, content, and behavior. Use Next.js only when the project already uses it; create a landing page only when explicitly requested.

ARCHITECTURE:
- Preserve the project's existing framework and router; use Next.js App Router guidance only when the project already uses Next.js
- Adapt component locations to the existing project; keep primitives, app-specific components, and utilities separated where its structure supports it
- Use CSS variables for theming via shadcn's built-in system

DESIGN PRINCIPLES:
- Minimalist with generous whitespace (py-24 to py-32 section spacing)
- Max-width container (max-w-6xl mx-auto) with responsive padding
- Typography hierarchy: text-5xl/6xl hero → text-3xl section titles → text-lg body
- Muted color palette with ONE bold accent color for CTAs
- Subtle micro-interactions on hover (scale, opacity transitions)
- Dark mode support via shadcn's theme provider

OPTIONAL LANDING-PAGE EXAMPLES — only when explicitly requested:
1. Navbar — sticky, transparent-to-solid on scroll, logo left, nav center, CTA button right
2. Hero — large headline (max 8 words), subtext (max 2 lines), primary CTA button + secondary ghost button, optional hero image or abstract illustration
3. Social proof — logo cloud of 5-6 partner/client logos in grayscale
4. Features — 3-column bento grid with icon, title, description per card using shadcn Card component
5. How it works — 3-step numbered process with connecting line
6. Testimonials — carousel or grid of 3 testimonial cards with avatar, quote, name, role
7. Pricing — 3-tier pricing table using shadcn Card, highlight the recommended plan with ring/border accent
8. FAQ — accordion using shadcn Accordion component
9. CTA — full-width section with headline, subtext, and primary action button
10. Footer — 4-column grid (brand, product links, company links, legal), copyright at bottom

COMPONENT USAGE:
- Button (primary, secondary, ghost, outline variants)
- Card, CardHeader, CardContent, CardFooter
- Accordion, AccordionItem, AccordionTrigger, AccordionContent
- Badge for labels/tags
- Separator for dividers
- NavigationMenu for navbar

CODE QUALITY:
- Fully responsive (mobile-first)
- Semantic HTML (section, nav, main, footer)
- Accessible (proper aria labels, keyboard navigation)
- Performant (lazy load images and use the project's existing font/image optimization)
- Keep component boundaries aligned with the existing app rather than creating components for hypothetical landing-page sections
```

---

### Aceternity UI

**Stack:** React, Next.js, Tailwind CSS, Framer Motion
**Install:** Copy-paste or `npx shadcn@latest add [component]`
**Site:** ui.aceternity.com

```
Migrate the existing UI to Aceternity UI where it fits, preserving its framework, routes, screens, content, and behavior. Use Next.js only when the project already uses it; create a landing page only when explicitly requested.

ARCHITECTURE:
- Preserve the project's existing framework and routing; use Next.js App Router only when the project already uses Next.js
- Organize copied Aceternity components and utilities within the existing project structure
- Install Framer Motion for animation engine

DESIGN PRINCIPLES:
- Dark theme as primary (bg-black/bg-slate-950 backgrounds)
- Dramatic contrast with glowing accents (cyan, purple, or emerald)
- Layered depth via gradients, glows, and glassmorphism
- Cinematic scroll-triggered animations with staggered reveals
- Generous padding (py-32+), large typography (text-6xl/7xl hero)
- Noise/grain texture overlays for visual richness

OPTIONAL LANDING-PAGE EXAMPLES — only when explicitly requested:
1. Navbar — floating navbar with backdrop blur, animated on scroll
2. Hero — use Aceternity's "Spotlight" or "Lamp" effect as background, massive headline with TextGenerateEffect or TypewriterEffect, gradient text on key words, two CTAs with HoverBorderGradient buttons
3. Logo cloud — use InfiniteMovingCards for auto-scrolling partner logos
4. Features — BentoGrid layout with animated cards, each card has BackgroundGradient or CardSpotlight hover effect
5. Product showcase — use Aceternity's 3DCard or ParallaxScroll for product screenshots/mockups
6. Testimonials — AnimatedTestimonials or InfiniteMovingCards with quote, avatar, name
7. How it works — use TracingBeam component for a connected step-by-step flow
8. Pricing — dark cards with GlowingStarsBackground, highlighted tier has animated border (MovingBorder)
9. CTA — full-width with BackgroundBeams or Meteors effect behind headline and button
10. Footer — clean 4-column layout with subtle separator

ANIMATION GUIDELINES:
- Page load: stagger hero elements (title → subtitle → buttons) with 0.15s delay each
- Scroll: use Framer Motion's whileInView for reveal animations (fade up + slight scale)
- Hover: cards lift (translateY -4px) with glow intensification
- Keep animations performant (use transform/opacity only, will-change where needed)
- Respect prefers-reduced-motion

CODE QUALITY:
- Mobile-first responsive design
- Lazy load heavy animation components
- Each section is a standalone component file
- Accessible despite heavy animation (aria labels, focus states)
```

---

### Magic UI

**Stack:** React, TypeScript, Tailwind CSS, Motion (Framer Motion)
**Install:** `npx shadcn@latest add [component]` (shadcn CLI compatible)
**Site:** magicui.design

```
Migrate the existing UI to Magic UI components where they fit, preserving its framework, routes, screens, content, and behavior. Use Next.js only when the project already uses it; create a landing page only when explicitly requested.

ARCHITECTURE:
- Preserve the project's existing framework and routing; use Next.js App Router only when the project already uses Next.js
- Install or copy Magic UI components using the method supported by the existing project
- Keep shared utilities and component locations consistent with the existing structure

DESIGN PRINCIPLES:
- Clean and modern, inspired by Linear/Vercel aesthetic
- Light or dark mode with smooth toggle transition
- Restrained animation — purposeful motion that guides attention, not distracts
- High contrast text, muted backgrounds (slate-50 light / slate-950 dark)
- Monospace or geometric sans-serif for headings, clean sans for body
- ONE signature color (blue-500, violet-500, or emerald-500) for accents

OPTIONAL LANDING-PAGE EXAMPLES — only when explicitly requested:
1. Navbar — clean horizontal nav, use MagicUI ShimmerButton for primary CTA
2. Hero — large headline with AnimatedGradientText on key phrase, NumberTicker for a live stat ("10,000+ users"), DotPattern or GridPattern as subtle background, two buttons (ShimmerButton primary + outline secondary)
3. Social proof — Marquee component for auto-scrolling logos horizontally
4. Features — use MagicCard components in a 3-column grid, each with icon + title + description, subtle hover glow effect
5. Bento showcase — BentoGrid layout showing product capabilities, mix of large and small tiles with different content types (text, mini-demos, stats)
6. Metrics — AnimatedList showing live activity feed OR NumberTicker showing key stats (users, uptime, speed)
7. Testimonials — Marquee of testimonial cards (vertical or horizontal scroll)
8. Pricing — 3 tiers with clean card design, NeonGradientCard for featured plan, BorderBeam on hover
9. CTA — centered layout with AnimatedShinyText headline, Particles or Meteors background effect
10. Footer — minimal 3-4 column grid, muted text, social icons

ANIMATION STRATEGY:
- Use BlurIn / FadeIn for section entrance animations
- NumberTicker for any statistics or metrics
- Marquee for any horizontally scrolling content
- Keep transitions under 600ms, use ease-out curves
- Mobile: reduce or disable particle/meteor effects for performance

CODE QUALITY:
- Fully responsive with mobile breakpoints
- Semantic HTML throughout
- Use next/font and next/image only when the existing project uses Next.js; otherwise use its current font loading and image optimization
- Preserve the app's existing screen/component boundaries; componentize sections only for a landing page the user explicitly requests
```

---

### DaisyUI

**Stack:** Tailwind CSS plugin (framework-agnostic)
**Install:** For Tailwind v4, use `npm i -D daisyui` and add `@import "tailwindcss";` and `@plugin "daisyui";` to the stylesheet; alternatively load a legacy config with `@config`. For Tailwind v3, use `npm i -D daisyui@^4` and register DaisyUI in `tailwind.config.js`.
**Site:** daisyui.com

```
Migrate the existing UI to DaisyUI classes, preserving its framework, routes, screens, content, and behavior. Create a landing page only when explicitly requested.

ARCHITECTURE:
- Framework of choice with Tailwind CSS + DaisyUI plugin
- Use DaisyUI's semantic class system (btn, card, hero, navbar, etc.)
- Select a DaisyUI theme using the configuration mechanism supported by the project's Tailwind version
- Keep styles and components in the existing project structure

DESIGN PRINCIPLES:
- Pick ONE DaisyUI theme as base (e.g., "winter" for clean light, "night" for dark, "corporate" for professional)
- Customize theme colors to match the brand (in the Tailwind v3 config or Tailwind v4 CSS plugin options)
- Minimalist layout with clean spacing (p-8 to p-16 sections)
- Let DaisyUI's built-in design system handle consistency
- Typography via DaisyUI's prose class for content sections

OPTIONAL LANDING-PAGE EXAMPLES — only when explicitly requested:
1. Navbar — "navbar" component with "dropdown" for mobile menu, "btn btn-primary" for CTA
2. Hero — "hero" component with "hero-content", large headline, subtext, "btn btn-primary" + "btn btn-ghost"
3. Social proof — logo row using "flex" with "opacity-50 grayscale" on images
4. Features — "card" components in a responsive grid, each with "card-body", uses "bg-base-200" for contrast
5. Stats — "stats" component with "stat" items showing key metrics
6. Steps — "steps" component (horizontal on desktop, vertical on mobile)
7. Testimonials — "chat" component styled as testimonials OR "card" grid with "avatar"
8. Pricing — "card" components with "badge badge-primary" for recommended plan
9. FAQ — "collapse" or "collapse-plus" components for expandable Q&A
10. Footer — "footer" component with 3-4 columns, "footer-title" for headings

CODE QUALITY:
- Fully responsive using Tailwind breakpoints
- Zero custom CSS needed (DaisyUI handles it)
- Accessible by default (DaisyUI follows ARIA patterns)
- Fast load times (CSS-only, no JS shipped)
- Works with any framework or plain HTML
```

---

### HeroUI (formerly NextUI)

**Stack:** React, Tailwind CSS, React Aria
**Install:** `npm i @heroui/react`
**Site:** heroui.com

```
Migrate the existing UI to HeroUI components, preserving its framework, routes, screens, content, and behavior. Use Next.js only when the project already uses it; create a landing page only when explicitly requested.

ARCHITECTURE:
- Preserve the project's existing framework and routing; add HeroUI's provider at the appropriate existing app root
- Import only needed components from @heroui/react (tree-shakeable)
- Keep component locations consistent with the existing project structure
- Use HeroUI's built-in theme system for consistent styling

DESIGN PRINCIPLES:
- Soft, modern aesthetic with rounded corners and smooth surfaces
- Light mode primary with dark mode support via HeroUI's theme toggle
- Subtle shadows and blur effects (HeroUI's built-in elevation system)
- Clean sans-serif typography, generous line heights
- Smooth transitions on all interactive elements (HeroUI provides these by default)

OPTIONAL LANDING-PAGE EXAMPLES — only when explicitly requested:
1. Navbar — HeroUI Navbar with NavbarBrand, NavbarContent, NavbarItem, NavbarMenuToggle for mobile
2. Hero — large headline, descriptive subtext, Button (color="primary" size="lg") + Button (variant="bordered")
3. Social proof — Avatar group for client logos or Chip components for trust badges
4. Features — Card components in grid, each with CardHeader, CardBody, use Divider between sections
5. Product demo — Tabs component to show different product views/features interactively
6. Testimonials — Card grid with User component (avatar + name + role) inside each card
7. Pricing — Card components with Chip for "Popular" badge, Listbox for feature lists
8. FAQ — if present or requested, use the Accordion API supported by the installed HeroUI version
9. CTA — centered section with Input + Button combo for email capture
10. Footer — clean grid with Link components, Divider above copyright

CODE QUALITY:
- Fully responsive with HeroUI's responsive props
- Accessible by default (React Aria foundation)
- Server-side rendering compatible
- Optimized bundle (import individual components)
- TypeScript strict mode
```

---

### Chakra UI

**Stack:** React, Emotion (CSS-in-JS)
**Install:** `npm i @chakra-ui/react`
**Site:** chakra-ui.com

```
Migrate the existing UI to Chakra UI v3, preserving its framework, routes, screens, content, and behavior. Use Next.js only when the project already uses it; create a landing page only when explicitly requested.

ARCHITECTURE:
- Preserve the project's existing framework and routing; wrap its existing app root in ChakraProvider with `value={system}` (or `defaultSystem` when no custom system is needed)
- Use Chakra UI v3's system and design tokens for brand customization
- Keep theme and component files in the existing project structure

DESIGN PRINCIPLES:
- Clean and warm aesthetic using Chakra's polished defaults
- Consistent spacing using Chakra's space scale (4, 8, 12, 16, 20, 24)
- Typography: use Chakra's Heading and Text components
- Use the project's existing color-mode provider; for Chakra UI v3, follow its current next-themes integration rather than removed v2 hooks
- Accessible-first: every component follows WAI-ARIA by default

OPTIONAL LANDING-PAGE EXAMPLES — only when explicitly requested:
1. Navbar — Flex with HStack, IconButton for mobile menu, Button for CTA
2. Hero — VStack centered, Heading size="4xl", Text, HStack with two Buttons
3. Social proof — HStack/Wrap of grayscale Image components
4. Features — SimpleGrid columns={{base:1, md:3}} of VStack cards with Icon, Heading, Text
5. Stats — if present or requested, use Chakra UI v3's Stat.Root, Stat.Label, Stat.ValueText, and Stat.HelpText
6. Testimonials — if present or requested, compose Chakra UI v3 Card.Root and Avatar.Root parts
7. Pricing — if present or requested, compose Chakra UI v3 Card.Root with Badge and List.Root/List.Item parts
8. FAQ — if present or requested, use Chakra UI v3's compound Accordion.Root, Accordion.Item, Accordion.ItemTrigger, and Accordion.ItemContent APIs
9. CTA — Box with bg gradient, VStack centered, Heading, Text, Button
10. Footer — SimpleGrid columns={{base:2, md:4}} with VStack, Heading, Link

V3 THEME SETUP:
import { createSystem, defaultConfig } from "@chakra-ui/react"

const system = createSystem(defaultConfig, {
  theme: {
    tokens: {
      colors: { brand: { 50: { value: "..." }, 500: { value: "..." }, 900: { value: "..." } } },
      fonts: { heading: { value: "Your Font" }, body: { value: "Your Font" } },
    },
  },
})

CODE QUALITY:
- Fully responsive using Chakra's responsive array/object syntax
- Use Chakra UI v3's documented color-mode integration instead of removed useColorModeValue
- Accessible by default
- TypeScript throughout with proper prop types
```

---

### Flowbite

**Stack:** Tailwind CSS (React, Vue, Svelte, Angular)
**Install:** Select the package for the existing framework: `flowbite-react` (React/Next.js), `flowbite-svelte` (Svelte), `flowbite-vue` (Vue), or `flowbite` (framework-agnostic Tailwind CSS). Follow that package's current installation guide.
**Site:** flowbite.com

```
Migrate the existing UI to Flowbite components for its current framework, preserving routes, screens, content, and behavior. Use Next.js only if the project already uses it; create a landing page only when explicitly requested.

ARCHITECTURE:
- Keep the project's existing framework and routing; do not convert it to Next.js or React.
- Choose the matching package and component API: `flowbite-react` for React/Next.js, `flowbite-svelte` for Svelte, `flowbite-vue` for Vue, or `flowbite` for framework-agnostic Tailwind projects. Verify current package instructions before installation.
- Use only the components and setup supported by the selected framework package; do not import React components into Svelte/Vue projects.

DESIGN PRINCIPLES:
- Business-professional aesthetic (clean, trustworthy, conversion-focused)
- Cool neutral palette (slate/gray) with strong brand accent
- Focus on readability and clear information hierarchy

OPTIONAL LANDING-PAGE EXAMPLES — only when explicitly requested (use components from the selected framework package):
1. Navbar — the selected framework package's Navbar and mobile-navigation components
2. Hero — a framework-appropriate heading, supporting text, and Button group
3. Social proof — row of client logos
4. Features — framework-appropriate Card components with icon badge, title, description
5. Content — alternating image + text rows
6. Testimonials — Blockquote or Card with the selected package's rating component
7. Pricing — Card, List, and Badge components from the selected framework package
8. FAQ — the selected framework package's Accordion component
9. Newsletter CTA — TextInput + Button in a styled Banner
10. Footer — the selected framework package's Footer and link-group components

CODE QUALITY:
- Fully responsive (components are responsive by default)
- Accessible (follows WAI-ARIA)
- Use the server-rendering pattern supported by the project's existing framework, if applicable
- Production-ready component patterns
```

---

### Preline UI

**Stack:** Tailwind CSS (HTML-first, React/Vue plugins)
**Install:** `npm i preline` + add plugin to tailwind.config
**Site:** preline.co

```
Migrate the existing UI to Preline UI patterns, preserving its framework, routes, screens, content, and behavior. Use Next.js only when the project already uses it; create a landing page only when explicitly requested.

ARCHITECTURE:
- Preserve the project's existing framework and routing; configure Preline with the Tailwind version already in use
- Use Preline's HTML component patterns (class-based, minimal JS)
- Use Preline's JavaScript behavior only for existing or requested interactive components

DESIGN PRINCIPLES:
- Modern SaaS aesthetic (clean lines, airy spacing, professional)
- Neutral base (white/slate) with vibrant accent for CTAs
- Large section padding (py-16 to py-24)

OPTIONAL LANDING-PAGE EXAMPLES — only when explicitly requested:
1. Navbar — header component with mega menu support, sticky on scroll
2. Hero — centered or split layout, large headline with gradient text, two CTA buttons
3. Social proof — logo ticker or static row with grayscale filter
4. Features — icon + text cards in 3-column grid
5. Tabs showcase — tab component showing different product features per tab
6. Testimonials — grid or slider of testimonial cards
7. Pricing — only if present or requested; use Preline's pricing table pattern
8. Stats — counter section with large numbers + labels
9. FAQ — only if present or requested; use the accordion component with smooth expand/collapse
10. CTA + Footer — email input + button CTA above multi-column footer

CODE QUALITY:
- Fully responsive with Tailwind breakpoints
- Accessible (follows ARIA standards)
- Lightweight (CSS + minimal JS)
- Works with any framework via HTML classes
```

---

### Park UI

**Stack:** React/Vue/Solid, Ark UI (headless), Tailwind CSS
**Install:** Copy-paste components (shadcn-style)
**Site:** park-ui.com

```
Migrate the existing UI to Park UI components, preserving its framework, routes, screens, content, and behavior. Use Next.js only when the project already uses it; create a landing page only when explicitly requested.

ARCHITECTURE:
- Preserve the project's existing framework and routing; use Park UI's compatible components
- Copy-paste components into the existing component structure
- Use the styling system already configured in the project

DESIGN PRINCIPLES:
- Polished and systematic (design-system quality)
- Neutral, sophisticated palette with deliberate accent usage
- Consistent spacing and sizing via Park UI's token scale
- Light/dark mode via Park UI's built-in theme tokens

OPTIONAL LANDING-PAGE EXAMPLES — only when explicitly requested:
1. Navbar — navigation components, clean horizontal layout, mobile drawer
2. Hero — Heading + Text with proper token sizing, Button pair (solid + outline)
3. Social proof — subtle logo row with muted styling
4. Features — Card components in grid with Icon, Heading, Text
5. Tabs showcase — Tabs component for interactive product feature display
6. Testimonials — Card-based layout with Avatar + quote
7. Pricing — Card grid with Badge for recommended tier
8. FAQ — Accordion component (Ark UI primitive, styled via Park UI)
9. CTA — centered section with Input + Button
10. Footer — grid layout with Link groups and Separator

CODE QUALITY:
- Fully responsive and accessible
- Ark UI headless primitives for rock-solid accessibility
- TypeScript strict mode
- Component-per-section architecture
```

---

### Origin UI

**Stack:** React, Tailwind CSS, shadcn/ui foundation
**Install:** Copy-paste (400+ free components)
**Site:** originui.com

```
Migrate the existing UI to Origin UI components, preserving its framework, routes, screens, content, and behavior. Use Next.js only when the project already uses it; create a landing page only when explicitly requested.

ARCHITECTURE:
- Preserve the project's existing framework and routing; use Origin UI where its shadcn-based components fit the current stack
- Copy-paste Origin UI components into the existing component structure
- Origin UI extends shadcn patterns with 400+ variant options

DESIGN PRINCIPLES:
- Professional and versatile (many style variants per component)
- Pick a cohesive subset of variants that match your brand
- Consistent spacing and typography aligned with shadcn's token system
- Focus on component quality and consistency over flashy animation

OPTIONAL LANDING-PAGE EXAMPLES — only when explicitly requested:
1. Navbar — choose from Origin UI's multiple navbar variants
2. Hero — select a hero variant (centered, split, with background pattern)
3. Social proof — logo cloud variant
4. Features — pick feature section variant (grid, list, bento, with images)
5. Content — alternating image/text sections
6. Testimonials — choose testimonial variant (cards, quotes, carousel)
7. Pricing — select pricing table variant (simple, comparison, with toggle)
8. FAQ — accordion variant
9. CTA — pick CTA variant (centered, with input, split layout)
10. Footer — choose footer variant (simple, multi-column, with newsletter)

CODE QUALITY:
- Fully responsive (all components are mobile-first)
- Accessible (shadcn/ui + Radix UI foundation)
- TypeScript throughout
- Minimal dependencies
```

---

### Headless UI

**Stack:** React or Vue, Tailwind CSS (by Tailwind Labs)
**Install:** Use `npm i @headlessui/react` for React or `npm i @headlessui/vue` for Vue 3; install only the package matching the existing framework.
**Site:** headlessui.com

```
Migrate the existing UI to Headless UI primitives, preserving its framework, routes, screens, content, and behavior. Use Next.js only when the project already uses it; create a landing page only when explicitly requested.

ARCHITECTURE:
- Preserve the project's existing framework and routing
- Use the package and component APIs matching the existing framework: `@headlessui/react` for React or `@headlessui/vue` for Vue 3; do not mix their APIs or convert frameworks
- Retain the project's existing styling system and component structure

DESIGN PRINCIPLES:
- Completely custom aesthetic — you control every pixel
- Minimalist, editorial-quality design (think Stripe, Linear, Vercel)
- Monochrome base with ONE signature accent color
- Large whitespace, precise typography, meticulous alignment
- Every interactive element is keyboard-navigable and screen-reader friendly

OPTIONAL LANDING-PAGE EXAMPLES — only when explicitly requested:
1. Navbar — custom with Headless UI Popover for dropdowns, Disclosure for mobile menu
2. Hero — pure Tailwind, dramatic typography, clean CTAs
3. Social proof — pure Tailwind logo row
4. Features — custom card grid, optional Tab component for tabbed showcase
5. Product showcase — TabGroup for interactive product views
6. Testimonials — pure Tailwind card grid
7. Pricing — RadioGroup for plan selection, Switch for monthly/annual toggle
8. FAQ — Disclosure component for accessible expand/collapse
9. CTA — pure Tailwind centered section
10. Footer — pure Tailwind grid layout

HEADLESS UI COMPONENTS TO LEVERAGE:
- React: use `Popover`, `Disclosure`, `Dialog`, `Transition`, `RadioGroup`, `Switch`, and `TabGroup` from `@headlessui/react`
- Vue 3: use `Popover`/`PopoverButton`/`PopoverPanel`, `Disclosure`/`DisclosureButton`/`DisclosurePanel`, `Dialog`, `TransitionRoot`/`TransitionChild`, `RadioGroup`, `Switch`, and `TabGroup` from `@headlessui/vue`
- Use each framework's documented component, state, and slot patterns

CODE QUALITY:
- 100% accessible (Headless UI's core guarantee)
- Fully responsive custom Tailwind design
- Keyboard navigation on all interactive elements
- TypeScript with proper generics
- Zero design dependencies — total creative control
```

---

### Cult UI

**Stack:** React, Next.js, Tailwind CSS, shadcn/ui foundation
**Install:** Copy-paste or CLI
**Site:** cult-ui.com

```
Migrate the existing UI to Cult UI components where they fit, preserving its framework, routes, screens, content, and behavior. Use Next.js only when the project already uses it; create a landing page only when explicitly requested.

ARCHITECTURE:
- Preserve the project's existing framework and routing; use Cult UI only where compatible with its current shadcn setup
- Follow the project's current full-stack architecture
- Use Cult UI's AI-specific blocks if building an AI product

DESIGN PRINCIPLES:
- Tech-forward, developer-centric aesthetic
- Dark mode primary with high-contrast accents
- Modern gradients and subtle glow effects
- Clean code-like typography (mono fonts for accents)
- Purposeful animation that communicates AI/tech sophistication

OPTIONAL LANDING-PAGE EXAMPLES — only when explicitly requested:
1. Navbar — modern floating nav with glass effect
2. Hero — bold headline with animated text effect, live demo or interactive element, gradient mesh background
3. Features — AI blocks for feature cards, animated icons or micro-interactions
4. Live demo — interactive component showing product in action
5. Code showcase — syntax-highlighted code examples using Cult UI's code block components
6. Testimonials — modern card layout with subtle animation
7. Pricing — clean tier comparison with feature matrix
8. Open source / community — GitHub stars counter, contributor avatars
9. CTA — compelling action section with email input or waitlist signup
10. Footer — developer-friendly footer with docs links, API reference, status page

CODE QUALITY:
- Full-stack patterns (API routes + client components)
- TypeScript strict mode throughout
- Accessible interactive components
- Production-ready architecture patterns
```

---

### Astryx

**Stack:** React, StyleX-authored components (no styling lock-in — override with Tailwind, CSS modules, or plain CSS)
**Install:** `npm install @astryxdesign/core` + a theme package (`@astryxdesign/theme-*`); optional `@astryxdesign/cli`
**Site:** astryx.atmeta.com · github.com/facebook/astryx (MIT, beta)

Meta's open design system: 160+ accessible, themeable React components, pre-built CSS
(no build plugin or PostCSS required), CSS-custom-property theming with seven ready
themes and dark mode built in. Two features matter for OpenWolf projects: component
**swizzling** (eject any component's source into the project for full control) and
**agent-ready docs** via the CLI/MCP — the docs are designed to be consumed by coding
agents, so migrations stay accurate.

```
Migrate this project's UI to Astryx (@astryxdesign/core).

SETUP:
- Install @astryxdesign/core and one theme package; wire the theme at the app root
- No build plugin/PostCSS needed — components ship with pre-built CSS
- If the Astryx CLI is available, use its agent-ready docs (CLI or MCP) as the
  source of truth for component APIs instead of guessing props

ARCHITECTURE:
- Replace bespoke primitives (buttons, inputs, dialogs, badges, switches) with
  Astryx components; keep app-specific composites as wrappers over Astryx parts
- Theme via CSS custom properties: generate a theme with the CLI or extend a
  ready-made one — derive tokens from the product's actual brand, never ship the
  default theme unmodified (see Design Principles above)
- Use swizzling only where a component must diverge structurally; prefer theming
  and composition first
- Dark mode through Astryx's built-in scheme switching; verify every migrated
  screen in both schemes

MIGRATION ORDER:
1. Theme tokens (colors, type scale, spacing) mapped from the existing design
2. Leaf primitives (Button, Input, Badge, Switch, Checkbox)
3. Composites (forms, dialogs, menus, tables)
4. Page templates — check Astryx's production templates before rebuilding a page
   from scratch, then de-genericize per the Design Principles

CODE QUALITY:
- Keep existing component APIs stable where consumers depend on them (wrap, don't break)
- TypeScript throughout; Astryx components are fully typed
- Accessibility is built in — don't undo it with overrides; test keyboard paths
```
