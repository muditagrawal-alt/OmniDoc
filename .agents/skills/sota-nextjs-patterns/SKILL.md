---
name: sota-nextjs-patterns
description: >-
  Version-aware Modern Next.js App Router Patterns for Next.js 16 Active LTS and Next.js 15 Maintenance LTS.
  Covers Server/Client boundaries, Server Actions, streaming, caching architectures (use cache), routing (proxy.ts vs middleware.ts),
  and defense-in-depth authorization. Activate when developing, refactoring, or architecting Next.js App Router applications.
---

# Modern Next.js App Router Patterns (Next.js 16 & 15 LTS)

## When to Use
Activate this skill whenever:
- Scaffolding, architecting, or upgrading Next.js App Router applications.
- Establishing boundary architecture between React Server Components (RSC) and Client Components.
- Configuring request routing and interception (`proxy.ts` vs `middleware.ts`).
- Designing caching strategies (`use cache`, Cache Components, tag-based revalidation).
- Implementing defense-in-depth authorization across server boundaries.
- Integrating real-time streaming, Server Actions, or AI SDK pipelines.

---

## 1. Version Awareness & Inspection
**Always inspect `package.json` before writing or modifying Next.js code.**
- Next.js 16 is **Active LTS**: Introduces `proxy.ts`, refined Cache Components, and enhanced Turbopack defaults.
- Next.js 15 is **Maintenance LTS**: Uses `middleware.ts`, experimental `use cache`, and async request APIs (`params`, `searchParams`, `cookies()`, `headers()`).

Never assume a single API target. Tailor code directly to the detected version.

---

## 2. Request Interception: `proxy.ts` vs `middleware.ts`

### New Next.js 16 Projects: Prefer `proxy.ts`
For fresh Next.js 16 implementations, use `proxy.ts` for network-level request rewrites, routing optimizations, and fast-path redirects:

```ts
// src/proxy.ts (Next.js 16+)
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

export function proxy(request: NextRequest) {
  // Fast-path routing and header decoration
  const response = NextResponse.next();
  response.headers.set('x-custom-routed', 'true');
  return response;
}
```

### Next.js 15 Projects: `middleware.ts`
Next.js 15 relies on `middleware.ts`. In existing codebases, do not force risky or breaking rewrites to `proxy.ts` unless the project is explicitly undertaking a major upgrade.

### ⚠️ Defense-in-Depth: Network Redirects Are NOT the Sole Authorization Check
**Proxy and middleware redirects are UX optimizations (early exits), NEVER the only authorization boundary.**
- Network-level checks can be bypassed or misconfigured.
- **Authorization must always be enforced at the server/data boundary**:
  - In Server Components before querying user-specific data.
  - In Server Actions before executing mutations.
  - In Route Handlers (`app/api/**/route.ts`) before processing payloads.
  - At the database / ORM query level using tenant-scoped identifiers.

```tsx
// app/dashboard/page.tsx - Server Component Data Boundary
import { auth } from '@/lib/auth';
import { redirect } from 'next/navigation';
import { db } from '@/lib/db';

export default async function DashboardPage() {
  const session = await auth();
  if (!session?.user) {
    redirect('/login');
  }

  // Tenant-scoped database query ensures data isolation
  const records = await db.documents.findMany({
    where: { organizationId: session.user.orgId }
  });

  return <DashboardView records={records} />;
}
```

---

## 3. Caching Architecture: `use cache` as Opt-In
Next.js provides Cache Components and the `use cache` directive to cache component subtrees or asynchronous functions.
- **`use cache` is OPT-IN**: Do NOT apply caching universally.
- Use `use cache` only when the data model fits:
  - Public marketing content, documentation, or static product listings.
  - Computationally heavy deterministic transforms (e.g. static syntax highlighting, math parsing).
- **Keep Dynamic/Personalized Data Uncached**:
  - User-specific dashboards, real-time activity feeds, and transactional carts must remain dynamic and request-evaluated.

```tsx
// Opt-in function-level caching with cache tags
import { unstable_cacheTag as cacheTag } from 'next/cache';

async function getGlobalSiteStats() {
  'use cache';
  cacheTag('site-stats');
  return await db.analytics.aggregate();
}
```

---

## 4. Balanced Data Fetching Strategy
Do not dogmatically forbid client-side fetching. Balance server-owned data with client-side requirements:

1. **Server Components (Default for Server-Owned Data)**:
   - Initial page data, secure database access, private API tokens, and static content.
   - Zero bundle size overhead on the client; eliminates client-side waterfall requests.
2. **Client-Side Fetching (TanStack Query / SWR for Valid Live Cases)**:
   - Polling live status updates (e.g. background processing job).
   - Optimistic UI updates (e.g. immediate like/save button feedback).
   - Real-time WebSocket or Server-Sent Events (SSE) subscriptions.
   - Client-driven infinite scrolling with dynamic client filters.

---

## 5. AI SDK Integration: No Pinned or Obsolete Models
When integrating AI pipelines (e.g. Vercel AI SDK):
- **Never pin obsolete or hallucinated model strings**: Do not hardcode deprecated models (e.g. legacy pinned snapshots).
- **Inspect Installed Versions**: Check `package.json` for installed SDK versions (`ai`, `@ai-sdk/google`, `@ai-sdk/openai`, etc.).
- **Verify Current Documentation**: Consult live documentation or MCP tools (`context7`) to use the latest streaming primitives (`streamText`, `createDataStreamResponse`).

```tsx
// app/api/chat/route.ts
import { streamText } from 'ai';
// Dynamically configure provider based on current environment and official SDK APIs
import { google } from '@ai-sdk/google';

export async function POST(req: Request) {
  const { messages } = await req.json();

  const result = streamText({
    // Use provider instance verified against project configuration
    model: google('gemini-2.5-flash'),
    messages,
  });

  return result.toDataStreamResponse();
}
```

---

## Anti-Patterns
- ❌ Never treat proxy or middleware redirects as the sole authorization check; enforce authorization at data access layers.
- ❌ Never force breaking rewrites between `middleware.ts` and `proxy.ts` without inspecting project version and needs.
- ❌ Never apply `use cache` blindly without evaluating user context and data volatility.
- ❌ Never forbid client-side fetching dogmatically when live client updates require SWR or TanStack Query.
- ❌ Never pin outdated AI model identifiers or deprecated provider APIs without checking installed packages.
- ❌ Never put `'use client'` on top-level layout files, forcing entire page trees into client bundles.
