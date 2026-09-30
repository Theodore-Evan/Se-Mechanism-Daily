-- Account-owned AI research maps built from starred paper snapshots.

create table if not exists public.user_research_maps (
  user_id uuid primary key references auth.users(id) on delete cascade,
  payload jsonb not null default '{}'::jsonb,
  source_count integer not null default 0,
  generated_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.research_map_requests (
  id bigint generated always as identity primary key,
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  status text not null default 'pending' check (status in ('pending', 'running', 'completed', 'failed')),
  requested_at timestamptz not null default now(),
  processed_at timestamptz,
  error_message text not null default ''
);

create index if not exists research_map_requests_pending_idx
  on public.research_map_requests (status, requested_at);

alter table public.user_research_maps enable row level security;
alter table public.research_map_requests enable row level security;

revoke all on table public.user_research_maps from anon, authenticated;
revoke all on table public.research_map_requests from anon, authenticated;
grant select on table public.user_research_maps to authenticated;
grant select, insert on table public.research_map_requests to authenticated;
grant usage, select on sequence public.research_map_requests_id_seq to authenticated;

drop policy if exists "read own research map" on public.user_research_maps;
create policy "read own research map" on public.user_research_maps
  for select to authenticated using ((select auth.uid()) = user_id);

drop policy if exists "read own research map requests" on public.research_map_requests;
create policy "read own research map requests" on public.research_map_requests
  for select to authenticated using ((select auth.uid()) = user_id);

drop policy if exists "create own research map requests" on public.research_map_requests;
create policy "create own research map requests" on public.research_map_requests
  for insert to authenticated with check ((select auth.uid()) = user_id);
