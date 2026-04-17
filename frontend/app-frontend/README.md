# GigShield Frontend Repository

Welcome to the unified GigShield Next.js App Router frontend infrastructure.

## Folder Structure

Our `app-frontend` workspace is organized into highly isolated, domain-specific modules:

```text
app-frontend/
├── app/                  # Next.js App Router (pages & layouts)
│   ├── admin/            # Admin Terminal portal
│   ├── hub/              # Hub Manager operational interface
│   ├── rider/            # Rider mobile-first PWA flow
│   ├── login/            # Auth role selection
│   └── page.tsx          # Public Landing Page
├── components/           # UI Component Library
│   ├── admin/            # Rigid, high-density Admin-only components
│   ├── hub/              # Dashboard components ("Precision Sentinel")
│   ├── rider/            # Consumer-facing mobile touch components
│   └── common/           # STRICTLY identical primitives (Avatars, standard Chips)
├── lib/                  # Utilities & Helpers
│   ├── api/              # API abstractions & fetches
│   ├── motion/           # Framer Motion config & safe transition wrappers
│   ├── theme/            # Tailwind theme tokens & configurations
│   └── utils/            # General generic utilities
└── public/               # Static assets
    └── icons/            # PWA manifest icons & core UI graphics
```

## Route Structure

We utilize Next.js nested routing to isolate layouts:
- `/`: The public gateway to the GigShield product suite.
- `/login/*`: Auth resolution paths per domain.
- `/rider/*`: A standalone Mobile-First Progressive Web App.
- `/hub/*`: Desktop-first ecosystem monitoring dashboard.
- `/admin/*`: Dense command-center interface.

## Strict Portal Separation

This application is **NOT a homogenized SaaS app**. We adhere to the **Strict UI Preservation** rule.
- Do not attempt to merge themes using generic "primary/secondary" utility classes if they cause visual drift.
- Buttons, cards, toggles, gradients, and nav bars should remain inside their respective `components/<portal>` directory unless they share 100% of their visual spacing and styling DNA.
- **Rider:** Cold, mobile-first, and expressive.
- **Hub:** Organic, editorial, "no-line" background shifts.
- **Admin:** Technical, brutalist, grid-locked, full-screen.

## Read-only Source Rule

The sibling folder `../source-ui/` acts as our ultimate source of design truth. It must **never** be edited.
1. `screen.png` is the visual target.
2. `code.html` defines the layout structure.
3. `DESIGN.md` enforces the component logic and theme bounds.
If there's ever a conflict between shared logic in Next.js and the original screen rendering, abandon DRY code in favor of visual precision.
