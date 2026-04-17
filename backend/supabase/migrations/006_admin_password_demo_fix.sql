-- Migration 006 — Fix demo admin password hash
-- Run AFTER 001..005.
-- Sets demo admin password to: GigShield@Admin123

UPDATE admin_users
SET password_hash = '$2b$12$jX3bhE.TjvG0Zzct0eBEru5aJJ58YalJiD/IennsaQR2iLcttqQhO'
WHERE username = 'admin';
