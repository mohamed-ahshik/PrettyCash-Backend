alter table public.profiles
  add column if not exists is_pro boolean not null default false,
  add column if not exists pro_source text;

alter table public.receipt_jobs
  add column if not exists user_id uuid references auth.users(id) on delete set null;

create table if not exists public.scan_usage (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  usage_date date not null,
  scan_count integer not null default 0 check (scan_count >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, usage_date)
);

create index if not exists scan_usage_user_date_idx
  on public.scan_usage(user_id, usage_date desc);

alter table public.scan_usage enable row level security;

drop policy if exists "own scan usage read" on public.scan_usage;
create policy "own scan usage read" on public.scan_usage
  for select using (auth.uid() = user_id);
