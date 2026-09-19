-- Day 19 now follows the same seven-station course as day 20.
-- Existing station-8 events are retained for audit history; the new profile
-- excludes that obsolete checkpoint, so scoring and future writes use station 7
-- as the final station before END.
lock table public.race_profiles, public.judge_station_accounts in share row exclusive mode;
do $$
begin
  if exists (
    select 1 from public.race_profiles
    where race_id in ('nanxi-race-20260919', 'nanxi-template-20260919')
      and station_count not in (7, 8)
  ) then
    raise exception 'Unexpected day-19 course: review configuration before migrating';
  end if;
end $$;

update public.race_profiles
set station_count = 7,
    checkpoints = '["START","STATION_2_START","STATION_3_START","STATION_4_START","STATION_5_START","STATION_6_START","STATION_7_START","END"]'::jsonb,
    updated_at = now()
where race_id in ('nanxi-race-20260919', 'nanxi-template-20260919')
  and station_count = 8;

update public.judge_station_accounts
set active = false, updated_at = now()
where race_id = 'nanxi-race-20260919' and role = 'station_8' and active;

notify pgrst, 'reload schema';
