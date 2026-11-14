-- Roles a board member held on earlier WiCS boards (e.g. {"Public Relations Chair"}), using
-- current board_role names where the role still exists. Lets Winnie find past holders of a role
-- to advise whoever holds it now (see backend/app/services/member_history.py).
alter table public.members
  add column if not exists previous_roles text[] not null default '{}';
