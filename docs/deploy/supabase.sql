-- Managed database for the hosted demo (Supabase free tier): chatbot logs and incident reviews.
-- Run once in Supabase > SQL Editor. The server writes with the service key (server side only);
-- row level security is on with no policies, so the public anon key can read or write nothing.

create table if not exists public.chat_logs (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  event text not null default 'chat',
  run_id text not null,
  source text not null,              -- model | register
  model text,
  latency_s real,
  total_s real,
  prompt_tokens integer,
  completion_tokens integer,
  failures jsonb not null default '[]',
  citations jsonb not null default '[]',
  question text,
  question_sha text,
  question_chars integer,
  client text                         -- salted hash of the client address, never the address
);

create table if not exists public.incident_reviews (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  run_id text not null,
  incident_id text not null,
  verdict text not null check (verdict in ('real', 'false_alarm', 'unsure')),
  reason text
);

alter table public.chat_logs enable row level security;
alter table public.incident_reviews enable row level security;

-- LLMOps at a glance: answers, model share, check failures and latency per day.
create or replace view public.chat_daily as
select date_trunc('day', created_at) as day,
       count(*) as answers,
       round(avg((source = 'model')::int)::numeric, 3) as model_share,
       percentile_cont(0.5) within group (order by latency_s) filter (where source = 'model') as median_latency_s,
       sum(coalesce(prompt_tokens, 0) + coalesce(completion_tokens, 0)) as tokens,
       count(*) filter (where jsonb_array_length(failures) > 0) as answers_with_failed_checks
from public.chat_logs group by 1 order by 1 desc;

-- Precision per rule from reviewers' verdicts (join incident ids to rules in the bundle).
create or replace view public.review_summary as
select run_id, verdict, count(*) as n from public.incident_reviews group by 1, 2 order by 1, 2;
