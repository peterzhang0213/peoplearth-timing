-- Change only the two Nanxi race days and their templates. Preserve custom counts
-- and refuse to reinterpret a completed nine-station course. Earlier stations
-- keep their checkpoint names and times; no timing events are rewritten.
do $$
begin
  if exists (
    select 1 from public.race_profiles r
    join public.timing_events e on e.race_id = r.race_id and e.status = 'accepted'
    where r.race_id in ('nanxi-race-20260919', 'nanxi-race-20260920')
      and r.station_count = 9
      and e.station_id in ('STATION_9_START', 'END')
  ) then
    raise exception 'Nanxi has station 9 or finish events: review the course change before migrating';
  end if;
end $$;

update public.race_profiles
set station_count = 8,
    checkpoints = '["START","STATION_2_START","STATION_3_START","STATION_4_START","STATION_5_START","STATION_6_START","STATION_7_START","STATION_8_START","END"]'::jsonb,
    updated_at = now()
where race_id in ('nanxi-race-20260919', 'nanxi-race-20260920',
                  'nanxi-template-20260919', 'nanxi-template-20260920')
  and station_count = 9;
