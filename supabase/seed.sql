-- Datos de DESARROLLO (solo se cargan con `supabase db reset` en local).
-- Credenciales locales (no usar en ningún otro entorno):
--   admin@munych.dev  / munych-admin-dev   (rol admin)
--   juez1@munych.dev  / munych-juez-dev    (rol judge)
--   juez2@munych.dev  / munych-juez-dev    (rol judge)

-- ---------------------------------------------------------------- organización

insert into app.organizations (id, name)
values ('00000000-0000-4000-8000-000000000001', 'MUNYCH Association');

-- ---------------------------------------------------------------- usuarios de Auth

insert into auth.users (
  instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
  raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
  confirmation_token, recovery_token, email_change_token_new, email_change
)
select
  '00000000-0000-0000-0000-000000000000',
  u.id,
  'authenticated',
  'authenticated',
  u.email,
  extensions.crypt(u.password, extensions.gen_salt('bf')),
  now(),
  '{"provider": "email", "providers": ["email"]}'::jsonb,
  '{}'::jsonb,
  now(),
  now(),
  '', '', '', ''
from (values
  ('10000000-0000-4000-8000-000000000001'::uuid, 'admin@munych.dev', 'munych-admin-dev'),
  ('20000000-0000-4000-8000-000000000001'::uuid, 'juez1@munych.dev', 'munych-juez-dev'),
  ('20000000-0000-4000-8000-000000000002'::uuid, 'juez2@munych.dev', 'munych-juez-dev')
) as u (id, email, password);

insert into auth.identities (
  id, user_id, provider_id, identity_data, provider, last_sign_in_at, created_at, updated_at
)
select
  gen_random_uuid(),
  u.id,
  u.id::text,
  jsonb_build_object('sub', u.id::text, 'email', u.email, 'email_verified', true),
  'email',
  now(),
  now(),
  now()
from auth.users u
where u.email in ('admin@munych.dev', 'juez1@munych.dev', 'juez2@munych.dev');

insert into app.user_roles (user_id, organization_id, role) values
  ('10000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000001', 'admin'),
  ('20000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000001', 'judge'),
  ('20000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-000000000001', 'judge');

insert into app.judges (user_id, organization_id, full_name) values
  ('20000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000001', 'Laura Méndez'),
  ('20000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-000000000001', 'Carlos Rivas');

-- ---------------------------------------------------------------- evento de ejemplo

insert into app.events (
  id, organization_id, slug, name, brand, venue, country_code, timezone, starts_on, ends_on, status
) values (
  '30000000-0000-4000-8000-000000000001',
  '00000000-0000-4000-8000-000000000001',
  'sd-mun-2026',
  'SD-MUN 2026',
  'grand_international',
  'Santo Domingo',
  'DO',
  'America/Santo_Domingo',
  '2026-10-09',
  '2026-10-11',
  'active'
);

-- Rúbrica por defecto (sección 6.1): escala 1–4.
insert into app.rubrics (id, event_id, name, scale_min, scale_max) values (
  '40000000-0000-4000-8000-000000000001',
  '30000000-0000-4000-8000-000000000001',
  'Rúbrica por defecto',
  1,
  4
);

insert into app.criteria (id, rubric_id, name, weight, position, level_descriptors)
select
  c.id,
  '40000000-0000-4000-8000-000000000001',
  c.name,
  c.weight,
  c.position,
  '{"1": "Inicial", "2": "En desarrollo", "3": "Competente", "4": "Excepcional"}'::jsonb
from (values
  ('41000000-0000-4000-8000-000000000001'::uuid, 'Conocimiento del tema y posición del país', 20.00, 1),
  ('41000000-0000-4000-8000-000000000002'::uuid, 'Oratoria (debate formal)', 20.00, 2),
  ('41000000-0000-4000-8000-000000000003'::uuid, 'Negociación y liderazgo (debate informal)', 20.00, 3),
  ('41000000-0000-4000-8000-000000000004'::uuid, 'Contribución a resoluciones', 15.00, 4),
  ('41000000-0000-4000-8000-000000000005'::uuid, 'Diplomacia y conducta', 15.00, 5),
  ('41000000-0000-4000-8000-000000000006'::uuid, 'Uso del reglamento', 10.00, 6)
) as c (id, name, weight, position);

update app.events
   set default_rubric_id = '40000000-0000-4000-8000-000000000001'
 where id = '30000000-0000-4000-8000-000000000001';

-- ---------------------------------------------------------------- comités

insert into app.committees (
  id, event_id, name, acronym, slug, type, delegation_mode, sessions_count, award_quotas
) values
  (
    '50000000-0000-4000-8000-000000000001',
    '30000000-0000-4000-8000-000000000001',
    'Primera Comisión de Desarme y Seguridad Internacional',
    'DISEC',
    'disec',
    'general_assembly',
    'single',
    2,
    '{"best_delegate": 1, "outstanding_delegate": 2, "honorable_mention": 2, "verbal_commendation": 3}'
  ),
  (
    '50000000-0000-4000-8000-000000000002',
    '30000000-0000-4000-8000-000000000001',
    'Consejo de Seguridad',
    'CSNU',
    'csnu',
    'security_council',
    'double',
    2,
    '{"best_delegate": 1, "outstanding_delegate": 1, "honorable_mention": 2, "verbal_commendation": 2}'
  );

insert into app.scoring_sessions (committee_id, number)
select c.id, n
from app.committees c
cross join generate_series(1, 2) as n
where c.event_id = '30000000-0000-4000-8000-000000000001';

-- DISEC (delegación individual)
with d as (
  insert into app.delegations (committee_id, country_code, institution)
  values
    ('50000000-0000-4000-8000-000000000001', 'MX', 'Colegio Ejemplo'),
    ('50000000-0000-4000-8000-000000000001', 'US', 'Instituto Norte'),
    ('50000000-0000-4000-8000-000000000001', 'FR', 'Liceo Francés'),
    ('50000000-0000-4000-8000-000000000001', 'BR', 'Colegio Sur'),
    ('50000000-0000-4000-8000-000000000001', 'JP', 'Instituto Oriente'),
    ('50000000-0000-4000-8000-000000000001', 'DO', 'Colegio Caribe')
  returning id, country_code, institution
)
insert into app.delegates (delegation_id, full_name, institution)
select d.id, n.full_name, d.institution
from d
join (values
  ('MX', 'Ana Pérez López'),
  ('US', 'John Smith'),
  ('FR', 'Camille Martin'),
  ('BR', 'João Silva'),
  ('JP', 'Yuki Tanaka'),
  ('DO', 'María Rodríguez')
) as n (country_code, full_name) on n.country_code = d.country_code;

-- CSNU (delegación doble)
with d as (
  insert into app.delegations (committee_id, country_code, institution)
  values
    ('50000000-0000-4000-8000-000000000002', 'CN', 'Colegio Ejemplo'),
    ('50000000-0000-4000-8000-000000000002', 'RU', 'Instituto Norte'),
    ('50000000-0000-4000-8000-000000000002', 'GB', 'Liceo Británico'),
    ('50000000-0000-4000-8000-000000000002', 'US', 'Colegio Sur'),
    ('50000000-0000-4000-8000-000000000002', 'FR', 'Instituto Oriente'),
    ('50000000-0000-4000-8000-000000000002', 'MX', 'Colegio Caribe')
  returning id, country_code, institution
)
insert into app.delegates (delegation_id, full_name, institution)
select d.id, n.full_name, d.institution
from d
join (values
  ('CN', 'Li Wei'), ('CN', 'Chen Jing'),
  ('RU', 'Iván Petrov'), ('RU', 'Olga Ivanova'),
  ('GB', 'Oliver Brown'), ('GB', 'Emily Clarke'),
  ('US', 'Mary Jones'), ('US', 'David Miller'),
  ('FR', 'Lucas Bernard'), ('FR', 'Léa Dubois'),
  ('MX', 'Sofía Hernández'), ('MX', 'Diego Torres')
) as n (country_code, full_name) on n.country_code = d.country_code;

-- ---------------------------------------------------------------- jueces asignados

insert into app.committee_judges (committee_id, judge_id, role) values
  ('50000000-0000-4000-8000-000000000001', '20000000-0000-4000-8000-000000000001', 'chair'),
  ('50000000-0000-4000-8000-000000000001', '20000000-0000-4000-8000-000000000002', 'judge'),
  ('50000000-0000-4000-8000-000000000002', '20000000-0000-4000-8000-000000000001', 'judge'),
  ('50000000-0000-4000-8000-000000000002', '20000000-0000-4000-8000-000000000002', 'chair');

insert into app.event_judges (event_id, judge_id) values
  ('30000000-0000-4000-8000-000000000001', '20000000-0000-4000-8000-000000000001'),
  ('30000000-0000-4000-8000-000000000001', '20000000-0000-4000-8000-000000000002');
