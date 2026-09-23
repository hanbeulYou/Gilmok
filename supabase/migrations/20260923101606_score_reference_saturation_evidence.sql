-- User-approved eighth metric is evidence only, never part of the cluster score.
comment on table public.score_reference is
  'Seoul reference distributions: 7 scoring metrics plus cluster.saturation evidence only. cluster.saturation is NOT used in score calculation; NULL if n_field or students is NULL or students=0.';
comment on column public.score_reference.axis_key is
  'Raw metric key. cluster.saturation = n_field/(students/1000), evidence percentile only; excluded from score calculation.';
