-- Day 20 only: seven timed stations plus the separate readiness/start area.
-- Lock against concurrent timing/config writes while checking the course is unused.
lock table public.race_profiles, public.timing_events, public.device_bindings,
  public.judge_station_accounts in share row exclusive mode;
do $$
begin
  if exists (
    select 1 from public.race_profiles r
    where r.race_id in ('nanxi-race-20260920', 'nanxi-template-20260920')
      and r.station_count not in (7, 8)
  ) then
    raise exception 'Unexpected day-20 course: review configuration before migrating';
  end if;
  if exists (
    select 1 from public.race_profiles r
    join public.timing_events e on e.race_id = r.race_id and e.status = 'accepted'
    where r.race_id in ('nanxi-race-20260920', 'nanxi-template-20260920') and r.station_count = 8
  ) then
    raise exception 'Day 20 already has timing history: review before changing the course';
  end if;
  if exists (
    select 1 from public.device_bindings
    where race_id in ('nanxi-race-20260920', 'nanxi-template-20260920') and assignment = 'STATION_8_START'
  ) then
    raise exception 'Day 20 has an obsolete station binding: review before changing the course';
  end if;
end $$;

update public.race_profiles
set station_count = 7,
    checkpoints = '["START","STATION_2_START","STATION_3_START","STATION_4_START","STATION_5_START","STATION_6_START","STATION_7_START","END"]'::jsonb,
    updated_at = now()
where race_id in ('nanxi-race-20260920', 'nanxi-template-20260920') and station_count = 8;

-- Keep account credentials for audit; station 7 now owns END dynamically.
update public.judge_station_accounts
set active = false, updated_at = now()
where race_id = 'nanxi-race-20260920' and role = 'station_8' and active;
notify pgrst, 'reload schema';
