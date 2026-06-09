CREATE TABLE todos (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT DEFAULT '',
  status TEXT NOT NULL,
  created_at INTEGER,
  updated_at INTEGER
);
INSERT INTO todos (id, title, description, status, created_at, updated_at)
VALUES ('todo-1', 'Plan the refactor', 'Map files first', 'done', 0, 0),
       ('todo-2', 'Implement parser', '', 'in_progress', 0, 0);
