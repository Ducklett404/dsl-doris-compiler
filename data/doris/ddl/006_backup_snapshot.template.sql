-- Requires a Doris Repository created by an administrator.
-- Replace placeholders only after validation passes.
BACKUP SNAPSHOT newzl.`__SNAPSHOT_LABEL__`
TO `__REPOSITORY__`
ON (hsj_stock_code_info, hsj_stock_hq_basic, hsj_stock_hq_ext, data_snapshot_registry)
PROPERTIES ("type" = "full");

