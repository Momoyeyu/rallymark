# Operations

## Bootstrap

Requirements are Docker with daemon access, Docker Compose 2.24.4 or newer, and an NVIDIA driver plus NVIDIA Container Toolkit on the GPU host. Python 3 runs the operator scripts. The source tree and .runtime/deploy.env must be available on the host.

~~~sh
make setup
make config-edit
# Edit .runtime/deploy.env: REGISTRY, WEIGHTS_PATH, GPU_DEVICE and WEB_PORT.
make doctor
make build VERSION=<commit-sha>
make config-check VERSION=<commit-sha>
make deploy VERSION=<commit-sha>
~~~

make setup generates unique credentials and leaves an existing file intact. Keep the environment file private. REGISTRY is currently the local image-name prefix rallymark. make deploy VERSION=<commit-sha> builds images on the deployment host before draining work; make rollback reuses the recorded previous images without rebuilding them. When a registry becomes available, configure REGISTRY and use LOCAL_BUILD=0 to pull published images. Use the API and algorithm database roles created by the PostgreSQL initialization script. Initialization runs once on a new database volume; changing a password in the environment file does not rotate an existing database role.

Weights are mounted read-only through WEIGHTS_PATH, which must contain the files recorded in services/algorithm/vendor/ftt/SHA256_MANIFEST.json. The initial host uses the 4090 UUID configured in deploy/.env.example. Only the frontend port is exposed. The first deployment is for the lab network/VPN and HTTP; set secure cookies and terminate HTTPS before using a public HTTPS endpoint.

## Local development

~~~sh
make setup
make dev
~~~

The development override selects the fake runner, uses a separate Compose project, and does not request a GPU. Development version records live under .runtime/dev/; production version records remain under .runtime/. For subsequent development operations, set RALLYMARK_MODE=dev; also set WEB_PORT=8181 when running beside production. It exercises upload, durable task processing and playback through the same API. make check and make test run the maintained validation commands. Production validation uses make smoke with BASE_URL pointing at a fake development deployment; make smoke-gpu additionally requires SMOKE_VIDEO pointing to the validated real sample.

## Update and recovery

make deploy VERSION=... builds versioned local images, validates Compose, rejects new analysis submissions and drains all existing queued and active work, runs versioned migrations and updates containers. If health checks fail, the previous recorded application version is restored. Schema migrations must remain backward-compatible because rollback does not run database downgrade operations. make rollback VERSION=... can explicitly select a previous version.

make config-check validates YAML before deployment. make config-apply drains active work and recreates the API and algorithm services. New jobs receive the new configuration; existing jobs retain their snapshots. View service status with make status and correlated logs with make logs SERVICE=api or SERVICE=algorithm-worker.

A changed model snapshot requires a real GPU smoke run before promotion. CI verifies CPU behavior, but a GPU inference test is a deployment check. Model weights are not part of container image layers or Git history.

## Data cleanup and backups

make data-clean previews expired business media and algorithm scratch data. Add APPLY=1 to execute, or VIDEO_ID=<uuid> to target a specific terminal video. The business cleanup command preserves ownership and task consistency and skips active work. Cleanup never removes the database, model weights or whole volumes.

make backup stores a PostgreSQL archive, deployment configuration, environment file and current version under backups/. Backup directories contain credentials and are private. Media and model volumes are not duplicated by this operation; back them up independently if required. make restore BACKUP=backups/<timestamp> drains work, restores the database and configuration, then starts services again against the retained media volume. Restore checks backup completeness, database credentials and locally available images for the recorded version before stopping services. It restores PostgreSQL within one transaction, writes the backed-up YAML to the active CONFIG_FILE path, and starts the recorded application version. Restore expects the same database role names and matching credentials from the backup environment file. Test restore on a separate deployment before relying on it operationally.

## CI

GitLab is the primary source and CI system. Merge requests and master run Python/frontend checks, PostgreSQL integration tests, contract drift checks and focused browser tests. CI currently neither builds images nor deploys. Makefile scripts build and deploy locally on the GPU machine. Registry publication can be added later without changing service boundaries. The project Docker runner is scoped to RallyMark.

make sync pushes the current branch to origin (GitLab), then github (private auxiliary repository), failing if either push fails. It does not rewrite or delete remote history.

The deployment host runs the project runner through the system service rallymark-gitlab-runner.service as sujunjie, with Docker group access. It starts at boot and restarts on failure. Check it with systemctl status rallymark-gitlab-runner and journalctl -u rallymark-gitlab-runner. Runner registration credentials stay in the user's private GitLab Runner configuration, outside this repository. Do not start a second nohup runner for the same registration.
