-- HOKA judges confirm the end of each station. START begins station 1,
-- STATION_2_START closes station 1, and END closes station 5.
-- Preserve all historical timing_events and only restore the race profile.
update public.race_profiles
set mode = 'station_checkpoints',
    station_count = 5,
    checkpoints = '["START", "STATION_2_START", "STATION_3_START", "STATION_4_START", "STATION_5_START", "END"]'::jsonb,
    entry_type = 'team',
    updated_at = timezone('utc', now())
where race_id in (
  'nfc-test-001',
  'hoka-race',
  'hoka-race-sh',
  'hoka-race-hz',
  'hoka-race-final',
  'hoka-race-demo'
)
and (
  mode is distinct from 'station_checkpoints'
  or station_count is distinct from 5
  or checkpoints is distinct from
    '["START", "STATION_2_START", "STATION_3_START", "STATION_4_START", "STATION_5_START", "END"]'::jsonb
  or entry_type is distinct from 'team'
);
