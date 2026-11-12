.DEFAULT_GOAL := help
export LOCAL_BUILD VERSION REGISTRY ENV_FILE VIDEO_ID APPLY SERVICE BACKUP RESTORE_VERSION CONFIG_FILE
export DEPLOY_HOST DEPLOY_DIR TARGET_FILE RALLYMARK_LOCAL RALLYMARK_MODE
OPS = python3 scripts/manage.py
.PHONY: help setup dev check test build deploy rollback status logs doctor config-edit config-check config-apply data-clean smoke smoke-gpu backup restore sync
help:
	@$(OPS) help
setup dev build deploy rollback status logs doctor config-edit config-check config-apply data-clean backup restore sync:
	@$(OPS) $@
check:
	@python3 scripts/check.py

test:
	@python3 scripts/check.py --tests
smoke:
	@python3 scripts/smoke.py
smoke-gpu:
	@python3 scripts/smoke.py --gpu
