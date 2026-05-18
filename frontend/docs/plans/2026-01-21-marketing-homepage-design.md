# Marketing Homepage Design

**Date:** 2026-01-21
**Project:** CSV Blog Generator
**Status:** Approved

## Overview

Design document voor een conversie-geoptimaliseerde marketing homepage met auth-aware navigatie en modern gradient design.

## Business Goals

- **Primary:** Product uitleggen en vertrouwen bouwen bij potentiële gebruikers
- **CTA:** Direct aanmelden (Sign up) voor nieuwe gebruikers
- **Value Proposition:** Snelheid en tijdsbesparing - "Genereer weken aan content in minuten"

## Color Palette

- **Brand Yellow:** `#FAB806` - Primair voor CTAs en accents
- **Brand Blue:** `#171d35` - Primaire donkere achtergrond
- **Brand Blue Light:** `#1a2340` - Gradient variant
- **Neutral:** Zwart (#000000) en Wit (#FFFFFF)

## Page Structure

1. **Fixed Navbar** (z-index 50, backdrop-blur)
2. **Hero Section** (min-h-[80vh])
3. **"Hoe het werkt"** - 3 stappen
4. **Features/Voordelen** - 4-column grid
5. **Social Proof** - Statistieken
6. **FAQ** - Accordion
7. **Footer**

## Component Specifications

### Navbar

**Type:** Server Component met Supabase SSR

```typescript
// src/components/Navbar.tsx
export async function Navbar() {
  const supabase = createServerClient()
  const { data: { user } } = await supabase.auth.getUser()
  // AuthButton received user prop and renders accordingly
}
```

**Behavior:**
- Links: Logo/merknaam
- Rechts: Auth-aware button
  - Niet ingelogd → "Sign up" (geel, `/signup`)
  - Ingelogd → "Dashboard" (outline, `/dashboard`)

**Styling:**
- `fixed top-0 w-full border-b backdrop-blur bg-background/50`
- Subtiel met transparante achtergrond

### Hero Section

**Layout:**
- Links: Headline + subheadline + CTA buttons
- Rechts: Illustratief element (CSV → blogs visual)

**Gradient Background:**
```css
bg-gradient-to-br from-[#171d35] via-[#1a2340] to-[#0d1117]
+ overlay: bg-gradient-to-t from-[#FAB806]/20 to-transparent
```

**Content:**
- **Headline (H1):** "Genereer weken aan blog content in minuten"
  - `text-5xl md:text-6xl font-bold text-white`
- **Subheadline:** "Upload je CSV, laat AI het werk doen..."
  - `text-xl md:text-2xl text-gray-300`
- **Primary CTA:** "Start gratis" → `/signup`
  - `bg-[#FAB806] text-[#171d35] hover:bg-[#e5a605]`
- **Secondary CTA:** "Meer info" → scroll naar secties
  - `bg-transparent border-2 border-white text-white`

### "Hoe het Werkt" Sectie

**Grid:** 3 kaarten in responsive grid

**Stappen:**
1. **Upload CSV** - "Sleep je CSV bestand met onderwerpen hierheen"
2. **AI doet het werk** - "Onze Celery worker verwerkt elke rij parallel met GPT-4o mini"
3. **Publiceer** - "Kopieer de gegenereerde blogs direct naar je CMS of download als JSON"

**Card Styling:**
- Witte achtergrond met shadow
- Hover: `hover:-translate-y-1` (lift effect)
- Gele accent rand bovenop: `border-t-4 border-[#FAB806]`

### Features/Voordelen

**Grid:** 4 columns op desktop, 2 op tablet, 1 op mobiel

**Items:**
- ⚡ Snelheid: "1000 blogs in < 30 minuten"
- 🤖 AI-kwaliteit: "GPT-4o mini voor consistent resultaat"
- 📊 Schaalbaar: "Van 1 tot 10.000+ blogs"
- 🔒 Veilig: "Data opgeslagen in Supabase, EU-compliant"

**Styling:**
- Icoon + titel + korte beschrijving per kaart
- Consistent met "Hoe het werkt" cards

### Social Proof

**Statistieken Row:**
- "500+ gebruikers"
- "50.000+ blogs gegenereerd"
- "4.8/5 rating"

**Implementatie:**
- Flexbox row met gelijke spacing
- Grote getallen, kleine labels
- Optioneel: testimonials carousel (later toe te voegen)

### FAQ Sectie

**Style:** Accordion (collapsible)

**Vragen:**
1. "Hoe lang duurt het voordat mijn blogs klaar zijn?"
2. "Kan ik mijn eigen prompts gebruiken?"
3. "Wat kost het?"
4. "Is mijn data veilig?"
5. "Kan ik annuleren?"

**Component:** Radix UI accordion of custom implementatie

## Technical Implementation

### Tailwind CSS v4 Setup

Add custom color tokens to `globals.css`:

```css
@theme {
  --color-brand-yellow: #FAB806;
  --color-brand-blue: #171d35;
  --color-brand-blue-light: #1a2340;
}
```

### Server Components Strategy

- **Navbar:** Server Component met Supabase SSR
- **Hero & Content:** Server Components (statisch)
- **FAQ:** Client Component (voor interactivity)
- **Testimonials:** Client Component (indien toegevoegd)

### Metadata & SEO

```typescript
export const metadata: Metadata = {
  title: "CSV Blog Generator | Genereer blogs in minuten",
  description: "Upload je CSV en genereer honderden SEO-geoptimaliseerde blogs met GPT-4o mini. Snel, schaalbaar, en betaalbaar.",
  openGraph: {
    title: "CSV Blog Generator",
    description: "Van CSV naar gepubliceerde blogs in minuten",
    type: "website",
  }
}
```

### Performance Best Practices

1. `next/image` voor alle afbeeldingen
2. Font preloading (Geist fonts)
3. Geen inline JS in initial render
4. Dynamic imports voor zware componenten
5. Minimal client-side JavaScript

## File Structure

```
src/
├── app/
│   ├── page.tsx              # Homepage (Server Component)
│   ├── layout.tsx            # Root layout
│   └── globals.css           # Global styles + theme
├── components/
│   ├── Navbar.tsx            # Server Component
│   ├── AuthButton.tsx        # Client Component (button)
│   ├── Hero.tsx              # Server Component
│   ├── HowItWorks.tsx        # Server Component
│   ├── Features.tsx          # Server Component
│   ├── SocialProof.tsx       # Server Component
│   ├── FAQ.tsx               # Client Component (accordion)
│   └── Footer.tsx            # Server Component
└── lib/
    └── supabase/
        └── server.ts         # Supabase server client
```

## Routing & Auth

- `/` - Publiek (home)
- `/login` - Publiek (login form)
- `/signup` - Publiek (signup form)
- `/dashboard` - Beschermd (redirect naar `/login` als niet ingelogd)

**Middleware:** Bestaande `proxy.ts` auth logic reeds geïmplementeerd

## Conversion Optimization

1. **Single CTA focus** - "Sign up" prominent in navbar en hero
2. **Trust signals** - Supabase logo, EU-compliant melding
3. **Social proof** - Statistieken met concrete getallen
4. **Reduced friction** - Direct naar `/signup` zonder tussenstappen
5. **Clear value prop** - Snelheid en tijdsbesparing in hero

## Future Enhancements

- Testimonials carousel met quotes van gebruikers
- Demo video in hero section
- Pricing sectie toevoegen
- Integratie logo's (WordPress, Ghost, etc.)
- Live preview van CSV upload functionaliteit

## Implementation Checklist

- [ ] Tailwind theme custom colors toevoegen
- [ ] Navbar Server Component maken met Supabase SSR
- [ ] AuthButton component maken (user prop based rendering)
- [ ] Hero section met gradient background
- [ ] "Hoe het werkt" - 3 cards grid
- [ ] Features - 4 columns grid
- [ ] Social proof - statistieken row
- [ ] FAQ accordion component
- [ ] Footer component
- [ ] SEO metadata configureren
- [ ] Responsive testen (mobiel, tablet, desktop)
- [ ] Accessibility check (contrast, ARIA labels)
- [ ] Performance test (Lighthouse)
