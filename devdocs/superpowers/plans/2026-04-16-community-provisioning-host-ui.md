# Community Provisioning — Host UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the host-side "Community Provisioning" React UI — a
new Settings section where hosts create/rename/delete homelabs,
regenerate Host-Keys, and manage per-API-key model allowlists.
One-shot plaintext key reveal modals. Live status badges from WS
events.

**Architecture:** A new feature folder
`frontend/src/features/community-provisioning/` containing the page,
sub-components, store, API client, and WS event handlers. Follows
the patterns of `frontend/src/app/components/llm-providers/` (existing
Connection management UI) — study that folder first for modals,
cards, list layout, and toast usage. Styling follows the
**user-facing opulent style** (consistent with other settings pages,
not Catppuccin-admin).

**Tech Stack:** React + Vite + TypeScript + Tailwind CSS, pnpm.
Testing with Vitest + React Testing Library. State management
matches whatever the existing Connections store uses (Zustand or
context — inspect and follow).

**Depends on:** Plan 1 (REST + events), Plan 3 (status events via WS).

**Parent spec:** `docs/superpowers/specs/2026-04-16-community-provisioning-design.md` §7.

---

## File Structure

**New files:**

- `frontend/src/features/community-provisioning/types.ts` — TypeScript mirrors of DTOs
- `frontend/src/features/community-provisioning/api.ts` — `fetch` wrapper around REST
- `frontend/src/features/community-provisioning/store.ts` — homelabs + api-keys state, event reducers
- `frontend/src/features/community-provisioning/CommunityProvisioningPage.tsx` — top-level page
- `frontend/src/features/community-provisioning/HomelabList.tsx`
- `frontend/src/features/community-provisioning/HomelabCard.tsx`
- `frontend/src/features/community-provisioning/HomelabCreateModal.tsx`
- `frontend/src/features/community-provisioning/HostKeyRevealModal.tsx` — one-shot plaintext
- `frontend/src/features/community-provisioning/ApiKeyList.tsx`
- `frontend/src/features/community-provisioning/ApiKeyCreateModal.tsx`
- `frontend/src/features/community-provisioning/ApiKeyRevealModal.tsx` — one-shot plaintext
- `frontend/src/features/community-provisioning/AllowlistEditor.tsx`
- `frontend/src/features/community-provisioning/events.ts` — WS event → store reducer
- `frontend/src/features/community-provisioning/__tests__/*.test.tsx`

**Modified files:**

- `frontend/src/app/pages/SettingsPage.tsx` (or equivalent settings router) — add nav entry + route
- The project's central event dispatcher (search for where existing `llm.connection.*` events are handled) — register the new `llm.homelab.*` and `llm.api_key.*` handlers

---

## Task 1: Type Definitions

**Files:**
- Create: `frontend/src/features/community-provisioning/types.ts`

- [ ] **Step 1: Write types mirroring the backend DTOs**

Create `frontend/src/features/community-provisioning/types.ts`:

```typescript
export type HomelabStatus = "active" | "revoked";

export interface HomelabEngineInfo {
  type: string;
  version: string | null;
}

export interface Homelab {
  homelab_id: string;
  display_name: string;
  host_key_hint: string;
  status: HomelabStatus;
  created_at: string;
  last_seen_at: string | null;
  last_sidecar_version: string | null;
  last_engine_info: HomelabEngineInfo | null;
  is_online: boolean;
}

export interface HomelabCreated extends Homelab {
  plaintext_host_key: string;
}

export interface HomelabHostKeyRegenerated extends Homelab {
  plaintext_host_key: string;
}

export type ApiKeyStatus = "active" | "revoked";

export interface ApiKey {
  api_key_id: string;
  homelab_id: string;
  display_name: string;
  api_key_hint: string;
  allowed_model_slugs: string[];
  status: ApiKeyStatus;
  created_at: string;
  revoked_at: string | null;
  last_used_at: string | null;
}

export interface ApiKeyCreated extends ApiKey {
  plaintext_api_key: string;
}

export interface CreateHomelabInput {
  display_name: string;
}

export interface UpdateHomelabInput {
  display_name?: string;
}

export interface CreateApiKeyInput {
  display_name: string;
  allowed_model_slugs: string[];
}

export interface UpdateApiKeyInput {
  display_name?: string;
  allowed_model_slugs?: string[];
}
```

- [ ] **Step 2: Verify TypeScript build**

Run: `pnpm --dir frontend tsc --noEmit`
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/community-provisioning/types.ts
git commit -m "Add Community Provisioning TypeScript types"
```

---

## Task 2: REST API Client

**Files:**
- Create: `frontend/src/features/community-provisioning/api.ts`

- [ ] **Step 1: Study the existing API-client pattern**

Search for an existing wrapper: `rg "fetch.*api/llm" frontend/src --files-with-matches`. Open one of the matching files (likely in `frontend/src/core/api/` or `frontend/src/app/components/llm-providers/`). Match its style for: auth header injection, error handling, JSON parsing.

- [ ] **Step 2: Implement the community-provisioning API**

Create `frontend/src/features/community-provisioning/api.ts`:

```typescript
import type {
  ApiKey,
  ApiKeyCreated,
  CreateApiKeyInput,
  CreateHomelabInput,
  Homelab,
  HomelabCreated,
  HomelabHostKeyRegenerated,
  UpdateApiKeyInput,
  UpdateHomelabInput,
} from "./types";

// If the project has a shared authed-fetch helper, import it here.
// Otherwise this is a minimal wrapper; harmonise with the codebase.
import { authedFetch } from "../../core/api/client"; // adjust path if different

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail: string | undefined;
    try {
      const body = await res.json();
      detail = body.detail;
    } catch {
      // ignore
    }
    throw new Error(`HTTP ${res.status}${detail ? `: ${detail}` : ""}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const base = "/api/llm/homelabs";

export const homelabsApi = {
  list: () => authedFetch(base).then(json<Homelab[]>),
  create: (body: CreateHomelabInput) =>
    authedFetch(base, { method: "POST", json: body }).then(json<HomelabCreated>),
  get: (id: string) => authedFetch(`${base}/${id}`).then(json<Homelab>),
  update: (id: string, body: UpdateHomelabInput) =>
    authedFetch(`${base}/${id}`, { method: "PATCH", json: body }).then(json<Homelab>),
  delete: (id: string) =>
    authedFetch(`${base}/${id}`, { method: "DELETE" }).then(json<void>),
  regenerateHostKey: (id: string) =>
    authedFetch(`${base}/${id}/regenerate-host-key`, { method: "POST" }).then(
      json<HomelabHostKeyRegenerated>,
    ),
};

export const apiKeysApi = {
  list: (homelabId: string) =>
    authedFetch(`${base}/${homelabId}/api-keys`).then(json<ApiKey[]>),
  create: (homelabId: string, body: CreateApiKeyInput) =>
    authedFetch(`${base}/${homelabId}/api-keys`, {
      method: "POST",
      json: body,
    }).then(json<ApiKeyCreated>),
  update: (homelabId: string, keyId: string, body: UpdateApiKeyInput) =>
    authedFetch(`${base}/${homelabId}/api-keys/${keyId}`, {
      method: "PATCH",
      json: body,
    }).then(json<ApiKey>),
  revoke: (homelabId: string, keyId: string) =>
    authedFetch(`${base}/${homelabId}/api-keys/${keyId}`, {
      method: "DELETE",
    }).then(json<void>),
  regenerate: (homelabId: string, keyId: string) =>
    authedFetch(`${base}/${homelabId}/api-keys/${keyId}/regenerate`, {
      method: "POST",
    }).then(json<ApiKeyCreated>),
};
```

If `authedFetch` does not exist with that signature, adapt — the
import path and request shape must match the rest of the codebase.
Common patterns: a `fetch`-like function that auto-adds `Authorization`
from the access-token store and supports a `json:` option.

- [ ] **Step 3: Smoke the TypeScript**

Run: `pnpm --dir frontend tsc --noEmit`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/community-provisioning/api.ts
git commit -m "Add REST client for homelabs and api-keys"
```

---

## Task 3: Store + Event Reducers

**Files:**
- Create: `frontend/src/features/community-provisioning/store.ts`
- Create: `frontend/src/features/community-provisioning/events.ts`

- [ ] **Step 1: Inspect the existing store pattern**

`rg "create\(" frontend/src/core/store --files-with-matches` (Zustand) or look for Redux/Context patterns. Follow what already exists.

- [ ] **Step 2: Implement the store**

Example with Zustand (adapt to the house pattern):

```typescript
// frontend/src/features/community-provisioning/store.ts
import { create } from "zustand";
import type { ApiKey, Homelab } from "./types";

interface State {
  homelabs: Record<string, Homelab>;
  apiKeysByHomelab: Record<string, Record<string, ApiKey>>;
  loaded: boolean;
  setHomelabs: (list: Homelab[]) => void;
  upsertHomelab: (h: Homelab) => void;
  removeHomelab: (id: string) => void;
  setApiKeys: (homelabId: string, keys: ApiKey[]) => void;
  upsertApiKey: (key: ApiKey) => void;
  removeApiKey: (homelabId: string, keyId: string) => void;
  setOnline: (homelabId: string, isOnline: boolean) => void;
  touchLastSeen: (homelabId: string, at: string) => void;
}

export const useCommunityProvisioningStore = create<State>((set) => ({
  homelabs: {},
  apiKeysByHomelab: {},
  loaded: false,
  setHomelabs: (list) =>
    set({
      homelabs: Object.fromEntries(list.map((h) => [h.homelab_id, h])),
      loaded: true,
    }),
  upsertHomelab: (h) =>
    set((s) => ({ homelabs: { ...s.homelabs, [h.homelab_id]: h } })),
  removeHomelab: (id) =>
    set((s) => {
      const { [id]: _gone, ...rest } = s.homelabs;
      const { [id]: _gone2, ...restKeys } = s.apiKeysByHomelab;
      return { homelabs: rest, apiKeysByHomelab: restKeys };
    }),
  setApiKeys: (homelabId, keys) =>
    set((s) => ({
      apiKeysByHomelab: {
        ...s.apiKeysByHomelab,
        [homelabId]: Object.fromEntries(keys.map((k) => [k.api_key_id, k])),
      },
    })),
  upsertApiKey: (key) =>
    set((s) => ({
      apiKeysByHomelab: {
        ...s.apiKeysByHomelab,
        [key.homelab_id]: {
          ...(s.apiKeysByHomelab[key.homelab_id] ?? {}),
          [key.api_key_id]: key,
        },
      },
    })),
  removeApiKey: (homelabId, keyId) =>
    set((s) => {
      const bucket = { ...(s.apiKeysByHomelab[homelabId] ?? {}) };
      delete bucket[keyId];
      return {
        apiKeysByHomelab: { ...s.apiKeysByHomelab, [homelabId]: bucket },
      };
    }),
  setOnline: (homelabId, isOnline) =>
    set((s) => {
      const h = s.homelabs[homelabId];
      if (!h) return s;
      return { homelabs: { ...s.homelabs, [homelabId]: { ...h, is_online: isOnline } } };
    }),
  touchLastSeen: (homelabId, at) =>
    set((s) => {
      const h = s.homelabs[homelabId];
      if (!h) return s;
      return {
        homelabs: { ...s.homelabs, [homelabId]: { ...h, last_seen_at: at } },
      };
    }),
}));
```

- [ ] **Step 3: Implement the event wiring**

Create `frontend/src/features/community-provisioning/events.ts`:

```typescript
import { useCommunityProvisioningStore } from "./store";

interface WSEvent {
  type: string;
  payload?: Record<string, unknown>;
  [k: string]: unknown;
}

export function handleCommunityProvisioningEvent(event: WSEvent): void {
  const st = useCommunityProvisioningStore.getState();
  switch (event.type) {
    case "llm.homelab.created":
    case "llm.homelab.updated":
    case "llm.homelab.host_key_regenerated":
      st.upsertHomelab((event as any).homelab);
      return;
    case "llm.homelab.deleted":
      st.removeHomelab((event as any).homelab_id);
      return;
    case "llm.homelab.status_changed":
      st.setOnline((event as any).homelab_id, (event as any).is_online);
      return;
    case "llm.homelab.last_seen":
      st.touchLastSeen((event as any).homelab_id, (event as any).last_seen_at);
      return;
    case "llm.api_key.created":
    case "llm.api_key.updated":
      st.upsertApiKey((event as any).api_key);
      return;
    case "llm.api_key.revoked":
      st.removeApiKey((event as any).homelab_id, (event as any).api_key_id);
      return;
  }
}
```

Register the handler in the project's central WS dispatcher. Grep
for existing `"llm.connection.created"` or similar to find where the
switch lives, and slot the community-provisioning handler alongside.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/community-provisioning/store.ts frontend/src/features/community-provisioning/events.ts
git commit -m "Add store and WS event wiring for community provisioning"
```

---

## Task 4: CommunityProvisioningPage + HomelabList + HomelabCard

**Files:**
- Create: `frontend/src/features/community-provisioning/CommunityProvisioningPage.tsx`
- Create: `frontend/src/features/community-provisioning/HomelabList.tsx`
- Create: `frontend/src/features/community-provisioning/HomelabCard.tsx`
- Create: `frontend/src/features/community-provisioning/__tests__/HomelabCard.test.tsx`

- [ ] **Step 1: Page shell with empty state + list**

Create `frontend/src/features/community-provisioning/CommunityProvisioningPage.tsx`:

```tsx
import { useEffect, useState } from "react";
import { homelabsApi } from "./api";
import { HomelabList } from "./HomelabList";
import { HomelabCreateModal } from "./HomelabCreateModal";
import { useCommunityProvisioningStore } from "./store";

export function CommunityProvisioningPage() {
  const homelabs = useCommunityProvisioningStore((s) => Object.values(s.homelabs));
  const loaded = useCommunityProvisioningStore((s) => s.loaded);
  const setHomelabs = useCommunityProvisioningStore((s) => s.setHomelabs);
  const [showCreate, setShowCreate] = useState(false);

  useEffect(() => {
    if (!loaded) {
      homelabsApi.list().then(setHomelabs);
    }
  }, [loaded, setHomelabs]);

  return (
    <section className="space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Community Provisioning</h1>
          <p className="mt-1 max-w-prose text-sm text-white/70">
            Share your home compute with people you invite. Run the Chatsune
            Sidecar on your GPU box, register it here, and issue API-Keys to
            the people you want to share with.
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="rounded-lg bg-amber-400 px-4 py-2 text-sm font-medium text-black hover:bg-amber-300"
        >
          Create homelab
        </button>
      </header>
      <HomelabList homelabs={homelabs} />
      {showCreate && (
        <HomelabCreateModal onClose={() => setShowCreate(false)} />
      )}
    </section>
  );
}
```

- [ ] **Step 2: HomelabList + HomelabCard**

Create `HomelabList.tsx`:

```tsx
import type { Homelab } from "./types";
import { HomelabCard } from "./HomelabCard";

export function HomelabList({ homelabs }: { homelabs: Homelab[] }) {
  if (!homelabs.length) {
    return (
      <div className="rounded-xl border border-white/10 p-8 text-center text-white/60">
        No homelabs yet. Create one to start sharing compute.
      </div>
    );
  }
  return (
    <ul className="space-y-3">
      {homelabs.map((h) => (
        <li key={h.homelab_id}>
          <HomelabCard homelab={h} />
        </li>
      ))}
    </ul>
  );
}
```

Create `HomelabCard.tsx`:

```tsx
import { useState } from "react";
import type { Homelab } from "./types";
import { homelabsApi } from "./api";
import { ApiKeyList } from "./ApiKeyList";
import { HostKeyRevealModal } from "./HostKeyRevealModal";

export function HomelabCard({ homelab }: { homelab: Homelab }) {
  const [expanded, setExpanded] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [nameDraft, setNameDraft] = useState(homelab.display_name);
  const [revealKey, setRevealKey] = useState<string | null>(null);

  async function saveName() {
    if (nameDraft.trim() && nameDraft !== homelab.display_name) {
      await homelabsApi.update(homelab.homelab_id, { display_name: nameDraft.trim() });
    }
    setRenaming(false);
  }

  async function regenerate() {
    if (!confirm("Generate a new Host-Key? The existing sidecar will drop and you'll need to update its .env.")) return;
    const res = await homelabsApi.regenerateHostKey(homelab.homelab_id);
    setRevealKey(res.plaintext_host_key);
  }

  async function del() {
    if (!confirm(`Delete "${homelab.display_name}"? All API-Keys become invalid, all consumer connections break.`)) return;
    await homelabsApi.delete(homelab.homelab_id);
  }

  const online = homelab.is_online;

  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0 flex-1">
          {renaming ? (
            <input
              autoFocus
              value={nameDraft}
              onChange={(e) => setNameDraft(e.target.value)}
              onBlur={saveName}
              onKeyDown={(e) => e.key === "Enter" && saveName()}
              className="w-full rounded bg-black/30 px-2 py-1"
            />
          ) : (
            <h3 className="truncate text-lg font-medium" onDoubleClick={() => setRenaming(true)}>
              {homelab.display_name}
            </h3>
          )}
          <div className="mt-1 flex items-center gap-3 text-xs text-white/60">
            <span>homelab://<code className="text-white/80">{homelab.homelab_id}</code></span>
            <span>host-key …{homelab.host_key_hint}</span>
            <span
              className={`rounded px-2 py-0.5 ${
                online ? "bg-emerald-500/20 text-emerald-300" : "bg-white/10 text-white/60"
              }`}
            >
              {online ? "online" : "offline"}
            </span>
          </div>
          {homelab.last_engine_info && (
            <div className="mt-1 text-xs text-white/50">
              {homelab.last_engine_info.type} {homelab.last_engine_info.version ?? ""} ·
              sidecar {homelab.last_sidecar_version ?? "?"}
            </div>
          )}
        </div>
        <div className="flex gap-2">
          <button onClick={() => setExpanded((x) => !x)} className="text-sm text-white/80 hover:text-white">
            {expanded ? "Hide keys" : "Manage keys"}
          </button>
          <button onClick={regenerate} className="text-sm text-white/80 hover:text-white">
            Regenerate host-key
          </button>
          <button onClick={del} className="text-sm text-red-400 hover:text-red-300">
            Delete
          </button>
        </div>
      </div>
      {expanded && (
        <div className="mt-4 border-t border-white/10 pt-4">
          <ApiKeyList homelabId={homelab.homelab_id} />
        </div>
      )}
      {revealKey && (
        <HostKeyRevealModal
          plaintext={revealKey}
          onClose={() => setRevealKey(null)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 3: Card render test**

Create `frontend/src/features/community-provisioning/__tests__/HomelabCard.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HomelabCard } from "../HomelabCard";
import type { Homelab } from "../types";

const sample: Homelab = {
  homelab_id: "Xk7bQ2eJn9m",
  display_name: "Wohnzimmer-GPU",
  host_key_hint: "9f2a",
  status: "active",
  created_at: "2026-04-16T10:00:00Z",
  last_seen_at: null,
  last_sidecar_version: null,
  last_engine_info: null,
  is_online: false,
};

describe("HomelabCard", () => {
  it("renders name, homelab-id, host-key hint, and offline badge", () => {
    render(<HomelabCard homelab={sample} />);
    expect(screen.getByText("Wohnzimmer-GPU")).toBeInTheDocument();
    expect(screen.getByText(/Xk7bQ2eJn9m/)).toBeInTheDocument();
    expect(screen.getByText(/9f2a/)).toBeInTheDocument();
    expect(screen.getByText("offline")).toBeInTheDocument();
  });

  it("shows online badge when is_online=true", () => {
    render(<HomelabCard homelab={{ ...sample, is_online: true }} />);
    expect(screen.getByText("online")).toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Run**

Run: `pnpm --dir frontend test -- HomelabCard`
Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/community-provisioning/
git commit -m "Add Community Provisioning page, list, and card"
```

---

## Task 5: HomelabCreateModal + HostKeyRevealModal

**Files:**
- Create: `HomelabCreateModal.tsx`
- Create: `HostKeyRevealModal.tsx`

- [ ] **Step 1: HomelabCreateModal**

```tsx
// frontend/src/features/community-provisioning/HomelabCreateModal.tsx
import { useState } from "react";
import { homelabsApi } from "./api";
import { HostKeyRevealModal } from "./HostKeyRevealModal";

export function HomelabCreateModal({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [reveal, setReveal] = useState<string | null>(null);

  async function submit() {
    const trimmed = name.trim();
    if (!trimmed) return;
    setBusy(true);
    try {
      const res = await homelabsApi.create({ display_name: trimmed });
      setReveal(res.plaintext_host_key);
    } finally {
      setBusy(false);
    }
  }

  if (reveal) {
    return <HostKeyRevealModal plaintext={reveal} onClose={onClose} />;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
      <div className="w-full max-w-md rounded-xl bg-neutral-900 p-6 shadow-2xl">
        <h2 className="text-xl font-semibold">Create homelab</h2>
        <p className="mt-2 text-sm text-white/70">
          Give it a name you'll recognise in the sidebar and in your sidecar's logs.
        </p>
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Wohnzimmer-GPU"
          className="mt-4 w-full rounded bg-black/50 p-2"
          maxLength={80}
        />
        <div className="mt-6 flex justify-end gap-3">
          <button onClick={onClose} className="text-white/70 hover:text-white">
            Cancel
          </button>
          <button
            disabled={busy || !name.trim()}
            onClick={submit}
            className="rounded bg-amber-400 px-4 py-2 font-medium text-black disabled:opacity-50"
          >
            Create
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: HostKeyRevealModal (one-shot)**

```tsx
// frontend/src/features/community-provisioning/HostKeyRevealModal.tsx
import { useState } from "react";

export function HostKeyRevealModal({
  plaintext,
  onClose,
}: {
  plaintext: string;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(plaintext);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
      <div className="w-full max-w-lg rounded-xl bg-neutral-900 p-6 shadow-2xl">
        <h2 className="text-xl font-semibold">Host-Key — shown once</h2>
        <p className="mt-2 text-sm text-amber-300">
          Copy this now. It will not be shown again. Paste it into your sidecar's
          <code className="mx-1 rounded bg-black/50 px-1">.env</code>
          under <code className="rounded bg-black/50 px-1">CHATSUNE_HOST_KEY=</code>
          before closing this dialog.
        </p>
        <pre className="mt-4 overflow-x-auto rounded bg-black/70 p-3 text-sm">
          {plaintext}
        </pre>
        <div className="mt-6 flex justify-end gap-3">
          <button onClick={copy} className="rounded bg-white/10 px-4 py-2">
            {copied ? "Copied" : "Copy to clipboard"}
          </button>
          <button
            onClick={onClose}
            className="rounded bg-amber-400 px-4 py-2 font-medium text-black"
          >
            I've saved it
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/community-provisioning/HomelabCreateModal.tsx frontend/src/features/community-provisioning/HostKeyRevealModal.tsx
git commit -m "Add homelab create and host-key reveal modals"
```

---

## Task 6: ApiKeyList + ApiKeyCreateModal + ApiKeyRevealModal

**Files:**
- Create: `ApiKeyList.tsx`, `ApiKeyCreateModal.tsx`, `ApiKeyRevealModal.tsx`

- [ ] **Step 1: ApiKeyList**

```tsx
// frontend/src/features/community-provisioning/ApiKeyList.tsx
import { useEffect, useState } from "react";
import { apiKeysApi } from "./api";
import { useCommunityProvisioningStore } from "./store";
import { ApiKeyCreateModal } from "./ApiKeyCreateModal";
import { ApiKeyRevealModal } from "./ApiKeyRevealModal";
import { AllowlistEditor } from "./AllowlistEditor";
import type { ApiKey } from "./types";

export function ApiKeyList({ homelabId }: { homelabId: string }) {
  const apiKeys = useCommunityProvisioningStore(
    (s) => Object.values(s.apiKeysByHomelab[homelabId] ?? {}),
  );
  const setApiKeys = useCommunityProvisioningStore((s) => s.setApiKeys);
  const [showCreate, setShowCreate] = useState(false);
  const [reveal, setReveal] = useState<string | null>(null);
  const [editingAllowlistFor, setEditingAllowlistFor] = useState<ApiKey | null>(null);

  useEffect(() => {
    apiKeysApi.list(homelabId).then((list) => setApiKeys(homelabId, list));
  }, [homelabId, setApiKeys]);

  async function revoke(key: ApiKey) {
    if (!confirm(`Revoke "${key.display_name}"? The consumer will lose access immediately.`)) return;
    await apiKeysApi.revoke(homelabId, key.api_key_id);
  }

  async function regenerate(key: ApiKey) {
    if (!confirm(`Regenerate "${key.display_name}"? The consumer must update their connection with the new key.`)) return;
    const res = await apiKeysApi.regenerate(homelabId, key.api_key_id);
    setReveal(res.plaintext_api_key);
  }

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <h4 className="text-sm font-medium">API-Keys</h4>
        <button
          onClick={() => setShowCreate(true)}
          className="rounded bg-white/10 px-3 py-1 text-xs hover:bg-white/20"
        >
          Create API-Key
        </button>
      </div>
      {apiKeys.length === 0 && <p className="text-sm text-white/50">No API-Keys yet.</p>}
      <ul className="space-y-2">
        {apiKeys.map((k) => (
          <li
            key={k.api_key_id}
            className="flex items-center justify-between rounded bg-black/20 p-2 text-sm"
          >
            <div>
              <div className="font-medium">{k.display_name}</div>
              <div className="text-xs text-white/60">
                …{k.api_key_hint} · {k.allowed_model_slugs.length} model
                {k.allowed_model_slugs.length === 1 ? "" : "s"} allowed
                {k.status === "revoked" && <span className="ml-2 text-red-400">revoked</span>}
              </div>
            </div>
            <div className="flex gap-3">
              <button onClick={() => setEditingAllowlistFor(k)} className="text-white/80 hover:text-white">
                Edit allowlist
              </button>
              <button onClick={() => regenerate(k)} className="text-white/80 hover:text-white">
                Regenerate
              </button>
              <button onClick={() => revoke(k)} className="text-red-400 hover:text-red-300">
                Revoke
              </button>
            </div>
          </li>
        ))}
      </ul>
      {showCreate && (
        <ApiKeyCreateModal
          homelabId={homelabId}
          onClose={() => setShowCreate(false)}
          onCreated={(plaintext) => {
            setShowCreate(false);
            setReveal(plaintext);
          }}
        />
      )}
      {reveal && <ApiKeyRevealModal plaintext={reveal} onClose={() => setReveal(null)} />}
      {editingAllowlistFor && (
        <AllowlistEditor
          homelabId={homelabId}
          apiKey={editingAllowlistFor}
          onClose={() => setEditingAllowlistFor(null)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: ApiKeyCreateModal**

```tsx
// frontend/src/features/community-provisioning/ApiKeyCreateModal.tsx
import { useState } from "react";
import { apiKeysApi } from "./api";

export function ApiKeyCreateModal({
  homelabId,
  onClose,
  onCreated,
}: {
  homelabId: string;
  onClose: () => void;
  onCreated: (plaintext: string) => void;
}) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    const trimmed = name.trim();
    if (!trimmed) return;
    setBusy(true);
    try {
      const res = await apiKeysApi.create(homelabId, {
        display_name: trimmed,
        allowed_model_slugs: [],
      });
      onCreated(res.plaintext_api_key);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
      <div className="w-full max-w-md rounded-xl bg-neutral-900 p-6 shadow-2xl">
        <h2 className="text-xl font-semibold">Create API-Key</h2>
        <p className="mt-2 text-sm text-white/70">
          Give it a name that tells you who it's for. You'll pick the allowed
          models immediately after — every key starts with no models, you
          tick them explicitly.
        </p>
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Bob (Testphase)"
          className="mt-4 w-full rounded bg-black/50 p-2"
          maxLength={80}
        />
        <div className="mt-6 flex justify-end gap-3">
          <button onClick={onClose} className="text-white/70 hover:text-white">
            Cancel
          </button>
          <button
            disabled={busy || !name.trim()}
            onClick={submit}
            className="rounded bg-amber-400 px-4 py-2 font-medium text-black disabled:opacity-50"
          >
            Create
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: ApiKeyRevealModal (one-shot, analogous to host-key)**

```tsx
// frontend/src/features/community-provisioning/ApiKeyRevealModal.tsx
import { useState } from "react";

export function ApiKeyRevealModal({
  plaintext,
  onClose,
}: {
  plaintext: string;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(plaintext);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
      <div className="w-full max-w-lg rounded-xl bg-neutral-900 p-6 shadow-2xl">
        <h2 className="text-xl font-semibold">API-Key — shown once</h2>
        <p className="mt-2 text-sm text-amber-300">
          Share this out-of-band with the person you're inviting. It will not
          be shown again.
        </p>
        <pre className="mt-4 overflow-x-auto rounded bg-black/70 p-3 text-sm">
          {plaintext}
        </pre>
        <div className="mt-6 flex justify-end gap-3">
          <button onClick={copy} className="rounded bg-white/10 px-4 py-2">
            {copied ? "Copied" : "Copy to clipboard"}
          </button>
          <button
            onClick={onClose}
            className="rounded bg-amber-400 px-4 py-2 font-medium text-black"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/community-provisioning/ApiKey*.tsx
git commit -m "Add API-key list, create and reveal modals"
```

---

## Task 7: AllowlistEditor

**Files:**
- Create: `AllowlistEditor.tsx`

The editor fetches the homelab's current model list (from the
existing model-list endpoint used by the model picker — grep
`/api/llm/connections/.*models` or similar; the community adapter's
`fetch_models` will feed the same endpoint once Plan 4 lands). For
now (before Plan 4), the editor shows the current allowlist as a
free-form slug input list, plus a list of slugs the host has
manually typed. Once Plan 4 ships and the community adapter serves
model metadata, the editor upgrades to show checkboxes from the live
model list.

- [ ] **Step 1: Implement a minimum viable editor**

```tsx
// frontend/src/features/community-provisioning/AllowlistEditor.tsx
import { useState } from "react";
import type { ApiKey } from "./types";
import { apiKeysApi } from "./api";

export function AllowlistEditor({
  homelabId,
  apiKey,
  onClose,
}: {
  homelabId: string;
  apiKey: ApiKey;
  onClose: () => void;
}) {
  const [slugs, setSlugs] = useState<string[]>([...apiKey.allowed_model_slugs]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);

  function add() {
    const v = draft.trim();
    if (!v) return;
    if (!slugs.includes(v)) setSlugs((xs) => [...xs, v]);
    setDraft("");
  }

  function remove(s: string) {
    setSlugs((xs) => xs.filter((x) => x !== s));
  }

  async function save() {
    setBusy(true);
    try {
      await apiKeysApi.update(homelabId, apiKey.api_key_id, { allowed_model_slugs: slugs });
      onClose();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
      <div className="w-full max-w-xl rounded-xl bg-neutral-900 p-6 shadow-2xl">
        <h2 className="text-xl font-semibold">Allowed models — {apiKey.display_name}</h2>
        <p className="mt-2 text-sm text-white/70">
          Only models in this list will be visible to the consumer using this API-Key.
          Enter each model's slug exactly as it appears in your sidecar
          (e.g. <code>llama3.2:8b</code>).
        </p>
        <div className="mt-4 flex gap-2">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && add()}
            placeholder="llama3.2:8b"
            className="flex-1 rounded bg-black/50 p-2"
          />
          <button onClick={add} className="rounded bg-white/10 px-3">
            Add
          </button>
        </div>
        <ul className="mt-4 space-y-2">
          {slugs.length === 0 && (
            <li className="rounded border border-dashed border-white/20 p-3 text-sm text-white/60">
              No models allowed. The consumer will see an empty model list.
            </li>
          )}
          {slugs.map((s) => (
            <li key={s} className="flex items-center justify-between rounded bg-black/30 p-2 text-sm">
              <code>{s}</code>
              <button onClick={() => remove(s)} className="text-red-400 hover:text-red-300">
                Remove
              </button>
            </li>
          ))}
        </ul>
        <div className="mt-6 flex justify-end gap-3">
          <button onClick={onClose} className="text-white/70 hover:text-white">
            Cancel
          </button>
          <button
            disabled={busy}
            onClick={save}
            className="rounded bg-amber-400 px-4 py-2 font-medium text-black disabled:opacity-50"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/features/community-provisioning/AllowlistEditor.tsx
git commit -m "Add initial allowlist editor (slug-entry)"
```

Note: once Plan 4 ships, upgrade the editor to fetch the live
model list via `/api/llm/connections/{id}/adapter/diagnostics` on
the host's own community connection, and present checkboxes.

---

## Task 8: Settings Route + WS Event Registration

**Files:**
- Modify: existing settings page/router (find via grep)
- Modify: existing WS event dispatcher (find via grep)

- [ ] **Step 1: Mount the page in settings**

Search for the existing Connections settings entry:
`rg "Connections" frontend/src/app/pages frontend/src/app/layouts`.
Add a sibling entry "Community Provisioning" that renders
`<CommunityProvisioningPage />`. Use the existing nav styling.

- [ ] **Step 2: Register event handler**

Search for the dispatcher:
`rg "llm.connection" frontend/src --type tsx --type ts`. Add the new
topic strings and route them through `handleCommunityProvisioningEvent`.

- [ ] **Step 3: Run the full frontend test + build**

Run: `pnpm --dir frontend test`
Run: `pnpm --dir frontend run build`
Both should succeed.

- [ ] **Step 4: Commit**

```bash
git add -A frontend/src
git commit -m "Wire Community Provisioning page into settings and WS dispatcher"
```

---

## Self-Review

1. Page, list, card, create modal, reveal modal, api-key list,
   api-key create modal, api-key reveal modal, allowlist editor —
   all exist under `frontend/src/features/community-provisioning/`.
2. Both reveal modals emphasise "shown once" + require explicit
   confirmation before dismissing.
3. The "Create API-Key" flow never auto-ticks all models (no
   convenience autofill, per the design spec's "no magic" rule).
4. Events `llm.homelab.*` and `llm.api_key.*` reach the store.
5. `pnpm --dir frontend run build` succeeds.
6. Page uses user-facing opulent style (not admin Catppuccin).
