-- Follow-up user decision after the fixed schema had already been applied locally.
comment on table public.living_pop is
  'Fixed coarse age means over each age column''s valid dates; NULL only if no valid age date. Total retains complete-period coverage. sample_days counts valid SPOP dates.';
