-- Aurora PostgreSQL 16 兼容初始化
-- 启用开发 & 生产都需要的扩展

CREATE EXTENSION IF NOT EXISTS "pgcrypto";        -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "btree_gin";        -- 复合索引支持
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements"; -- 慢查询诊断

-- 开发期 log 级别调高（生产注掉）
ALTER SYSTEM SET log_statement = 'ddl';
ALTER SYSTEM SET log_min_duration_statement = 100;  -- >100ms 记录
SELECT pg_reload_conf();
