-- nfc-test-001 is the legacy two-reader NFC simulation, not an HOKA race.
-- Restore only its profile; no participant or timing event data is changed.
update public.race_profiles
set mode = 'two_reader_auto',
    station_count = 8,
    checkpoints = '["START", "STATION_1_ENTER", "STATION_1_EXIT", "STATION_2_ENTER", "STATION_2_EXIT", "STATION_3_ENTER", "STATION_3_EXIT", "STATION_4_ENTER", "STATION_4_EXIT", "STATION_5_ENTER", "STATION_5_EXIT", "STATION_6_ENTER", "STATION_6_EXIT", "STATION_7_ENTER", "STATION_7_EXIT", "STATION_8_ENTER", "END"]'::jsonb,
    entry_type = 'individual',
    updated_at = timezone('utc', now())
where race_id = 'nfc-test-001'
  and (
    mode is distinct from 'two_reader_auto'
    or station_count is distinct from 8
    or checkpoints is distinct from
      '["START", "STATION_1_ENTER", "STATION_1_EXIT", "STATION_2_ENTER", "STATION_2_EXIT", "STATION_3_ENTER", "STATION_3_EXIT", "STATION_4_ENTER", "STATION_4_EXIT", "STATION_5_ENTER", "STATION_5_EXIT", "STATION_6_ENTER", "STATION_6_EXIT", "STATION_7_ENTER", "STATION_7_EXIT", "STATION_8_ENTER", "END"]'::jsonb
    or entry_type is distinct from 'individual'
  );
