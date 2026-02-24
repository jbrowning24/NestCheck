# claude.md Template

> Save this file as `claude.md` in your project root. Claude Code and Cursor will automatically read it for project context.

---

```markdown
# Project: [YOUR PROJECT NAME]

## Overview
[2-3 sentences about what this project is]

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | [React/Next.js/Vue/etc.] |
| Styling | [Tailwind/CSS Modules/etc.] |
| State | [Zustand/Redux/React Query/etc.] |
| Backend | [Node/Supabase/Firebase/etc.] |
| Database | [PostgreSQL/MongoDB/etc.] |
| Auth | [Supabase Auth/Clerk/Auth0/etc.] |
| Hosting | [Vercel/Railway/AWS/etc.] |

## Project Structure

```
src/
├── app/              # Next.js app router pages
├── components/       # Reusable UI components
│   ├── ui/          # Base components (buttons, inputs)
│   └── features/    # Feature-specific components
├── lib/             # Utilities and helpers
├── services/        # API/external service integrations
├── stores/          # State management
├── types/           # TypeScript type definitions
└── hooks/           # Custom React hooks
```

## Coding Standards

### General
- TypeScript for all new files
- Prefer `const` over `let`
- Use descriptive variable names
- Keep functions small and single-purpose

### Components
- Functional components only (no class components)
- Use custom hooks to extract logic
- Props interfaces defined above component
- Memoize expensive computations

### Naming Conventions
- Files: `kebab-case.ts` or `PascalCase.tsx` for components
- Variables: `camelCase`
- Types/Interfaces: `PascalCase`
- Constants: `SCREAMING_SNAKE_CASE`

### No-No's
- No `console.log` in production code (use logger)
- No `any` types
- No `@ts-ignore`
- No inline styles (use Tailwind)
- No hardcoded strings (use constants)

## Development Workflow

1. **Create Issue** - Capture idea in Linear
2. **Explore** - Understand before building
3. **Plan** - Create markdown plan with tasks
4. **Execute** - Implement step by step
5. **Review** - Self-review + peer review
6. **Document** - Update docs if needed

## Key Files to Know

| File | Purpose |
|------|---------|
| `src/lib/supabase.ts` | Supabase client setup |
| `src/services/api.ts` | API helper functions |
| `src/stores/user.ts` | User state management |
| `src/types/database.ts` | Database type definitions |

## Common Patterns

### Data Fetching
We use React Query for server state:
```typescript
const { data, isLoading } = useQuery({
  queryKey: ['items', id],
  queryFn: () => fetchItem(id),
})
```

### State Management
We use Zustand for client state:
```typescript
const useStore = create<State>((set) => ({
  count: 0,
  increment: () => set((s) => ({ count: s.count + 1 })),
}))
```

### Error Handling
Always wrap async operations:
```typescript
try {
  await riskyOperation()
} catch (error) {
  logger.error('Operation failed', { error })
  toast.error('Something went wrong')
}
```

## Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL | `https://xxx.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Public Supabase key | `eyJhbGc...` |
| `STRIPE_SECRET_KEY` | Stripe API key (server only) | `sk_live_...` |

## Decision Log

Track important architectural decisions here:

| Date | Decision | Rationale |
|------|----------|-----------|
| 2025-01-15 | Chose Zustand over Redux | Simpler API, less boilerplate for our needs |
| 2025-01-20 | Using RLS for auth | Row-level security at database layer |

## Known Issues / Tech Debt

- [ ] Need to add proper error boundaries
- [ ] Image optimization not configured
- [ ] Missing loading states on some pages

## Resources

- [Design System Figma](link)
- [API Documentation](link)
- [Product Requirements](link)
```

---

## Tips for Maintaining claude.md

1. **Keep it current** - Update when major changes happen
2. **Decision log is gold** - Every "why" you record saves future time
3. **Be specific** - "We use X" is better than "Consider using X"
4. **Include patterns** - Real code snippets from your project
5. **List the no-no's** - What you DON'T want is as important as what you want
