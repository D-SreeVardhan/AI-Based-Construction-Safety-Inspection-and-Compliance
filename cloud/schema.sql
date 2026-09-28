create extension if not exists vector;

create table if not exists runs (
  id text primary key,
  status text not null,
  created_at timestamptz not null,
  completed_at timestamptz,
  clip_name text not null,
  manifest jsonb not null,
  video_path text,
  report_path text,
  inserted_at timestamptz not null default now()
);

create table if not exists incidents (
  id text primary key,
  run_id text not null references runs(id) on delete cascade,
  rule_id text not null,
  status text not null,
  payload jsonb not null,
  inserted_at timestamptz not null default now()
);

create index if not exists incidents_run_id_idx on incidents(run_id);
create index if not exists incidents_rule_id_idx on incidents(rule_id);

create table if not exists clause_chunks (
  id text primary key,
  catalogue_sha256 text not null,
  rule_ids text[] not null,
  clause_ref text not null,
  title text not null,
  text text not null,
  source text not null,
  source_url text not null,
  retrieved_on date not null,
  sha256 text not null,
  embedding vector(768),
  inserted_at timestamptz not null default now()
);

create index if not exists clause_chunks_rule_ids_idx on clause_chunks using gin(rule_ids);
create index if not exists clause_chunks_text_fts_idx
  on clause_chunks using gin(to_tsvector('english', clause_ref || ' ' || title || ' ' || text));

create table if not exists briefings (
  incident_id text primary key references incidents(id) on delete cascade,
  run_id text not null references runs(id) on delete cascade,
  rule_id text not null,
  refused boolean not null default false,
  payload jsonb not null,
  inserted_at timestamptz not null default now()
);

create index if not exists briefings_run_id_idx on briefings(run_id);

create table if not exists chat_messages (
  id bigserial primary key,
  run_id text not null references runs(id) on delete cascade,
  question text not null,
  answer text not null,
  payload jsonb not null,
  inserted_at timestamptz not null default now()
);

create index if not exists chat_messages_run_id_idx on chat_messages(run_id);

alter table runs enable row level security;
alter table incidents enable row level security;
alter table clause_chunks enable row level security;
alter table briefings enable row level security;
alter table chat_messages enable row level security;

drop policy if exists "public read runs" on runs;
create policy "public read runs" on runs for select using (true);

drop policy if exists "public read incidents" on incidents;
create policy "public read incidents" on incidents for select using (true);

drop policy if exists "public read clause chunks" on clause_chunks;
create policy "public read clause chunks" on clause_chunks for select using (true);

drop policy if exists "public read briefings" on briefings;
create policy "public read briefings" on briefings for select using (true);

drop policy if exists "public read chat messages" on chat_messages;
create policy "public read chat messages" on chat_messages for select using (true);
