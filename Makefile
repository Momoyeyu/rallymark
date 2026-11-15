.DEFAULT_GOAL := help
export MEDIA_STORAGE ALGORITHM_STORAGE STORAGE_MOUNT STORAGE_ROOT PREVIEW_DATA_PATH
export CONFIG_SCOPE GPU_POOL_FILE GPU_CDI_DEVICE
export LOCAL_BUILD VERSION REGISTRY ENV_FILE VIDEO_ID APPLY SERVICE BACKUP RESTORE_VERSION CONFIG_FILE
export DEPLOY_HOST DEPLOY_DIR TARGET_FILE RALLYMARK_LOCAL RALLYMARK_MODE
OPS = python3 scripts/manage.py
.PHONY: help setup dev check test build deploy rollback status logs doctor config-edit config-check config-apply data-clean smoke smoke-gpu backup restore sync
help:
	@$(OPS) help
setup dev build deploy rollback status logs doctor config-edit config-check config-apply data-clean backup restore sync storage-migrate:
	@$(OPS) $@
check:
	@python3 scripts/check.py

test:
	@python3 scripts/check.py --tests
smoke:
	@python3 scripts/smoke.py
smoke-gpu:
	@python3 scripts/smoke.py --gpu

# Static six-match preview: same UI, separate release and port.
.PHONY: preview-export preview-build preview-deploy preview-status preview-logs
preview-export:
	python3 scripts/preview.py "$(or $(EXPERIMENT),.runtime/preview-source)" .runtime/preview-data
preview-build:
	cd apps/web && pnpm build:preview
preview-deploy preview-status preview-logs:
	$(OPS) $@
