import hashlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "rallymark_manage", Path(__file__).resolve().parents[1] / "scripts/manage.py"
)
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)


class OpsReview(unittest.TestCase):
    def setUp(self):
        remote = patch.object(ops, "forward_remote", return_value=False)
        remote.start()
        self.addCleanup(remote.stop)

    def test_disabled_gpu_mode_skips_hardware_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.dict(os.environ, {"GPU_MODE": "disabled"}, clear=True),
                patch.object(ops, "version_directory", return_value=Path(directory)),
                patch.object(ops, "compose"),
                patch.object(ops, "gpu_preflight") as gpu,
                patch.object(ops, "prepare_weights") as prepare,
                patch.object(ops, "drain"),
                patch.object(ops, "migrate"),
                patch.object(ops, "business"),
            ):
                ops.deploy("maintenance", build=True)
                gpu.assert_not_called()
                prepare.assert_not_called()

    def test_missing_weights_are_prepared_before_draining(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {}, clear=True),
            patch.object(ops, "version_directory", return_value=Path(directory)),
            patch.object(ops, "compose"),
            patch.object(ops, "gpu_preflight"),
            patch.object(ops, "prepare_weights", side_effect=RuntimeError("download failed")) as prepare,
            patch.object(ops, "drain") as drain,
        ):
            with self.assertRaisesRegex(RuntimeError, "download failed"):
                ops.deploy("v2", build=True)
            prepare.assert_called_once_with(ops.ROOT)
            drain.assert_not_called()

    def test_prepare_weights_downloads_only_missing_weights(self):
        from model_assets import MANIFEST, prepare_weights

        payload = b"verified model bytes"
        expected = {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            weights = root / "cache"
            weights.mkdir()
            (weights / "present.pt").write_bytes(payload)
            manifest = root / MANIFEST
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({
                "weights/present.pt": expected,
                "weights/missing.pth": expected,
                "ocr/models/optional.onnx": expected,
                "source_code_and_ocr.tar.gz": expected,
            }))
            with (
                patch.dict(os.environ, {"WEIGHTS_PATH": "../cache"}, clear=True),
                patch("model_assets.urlopen", return_value=io.BytesIO(payload)) as download,
            ):
                prepare_weights(root)
                prepare_weights(root)
            download.assert_called_once_with(
                "https://www.modelscope.ai/models/momoyeyu/rallymark/resolve/ftt-weights-v1/weights/missing.pth",
                timeout=60,
            )
            self.assertEqual((weights / "missing.pth").read_bytes(), payload)
            self.assertEqual(sorted(p.name for p in weights.iterdir()), ["missing.pth", "present.pt"])

    def test_prepare_weights_does_not_publish_a_corrupt_download(self):
        from model_assets import MANIFEST, prepare_weights

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            weights = root / "cache"
            manifest = root / MANIFEST
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({
                "weights/missing.pth": {"bytes": 4, "sha256": hashlib.sha256(b"good").hexdigest()},
            }))
            with (
                patch.dict(os.environ, {"WEIGHTS_PATH": str(weights)}, clear=True),
                patch("model_assets.urlopen", return_value=io.BytesIO(b"bad!")),
            ):
                with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                    prepare_weights(root)
            self.assertEqual(list(weights.iterdir()), [])

    def test_disabled_compose_has_no_development_override(self):
        with (
            patch.dict(os.environ, {"GPU_MODE": "disabled"}, clear=True),
            patch.object(ops, "run") as run,
        ):
            ops.compose("config")
            command = [str(part) for part in run.call_args.args[0]]
            self.assertIn(str(ops.ROOT / "deploy/compose.unavailable.yaml"), command)
            self.assertNotIn(str(ops.ROOT / "deploy/compose.dev.yaml"), command)

    def test_invalid_algorithm_configuration_does_not_drain(self):
        def compose(*args, **kwargs):
            if args[0] == "run" and "algorithm" in args:
                raise subprocess.CalledProcessError(1, args)

        with (
            patch.dict(os.environ, {"VERSION": "v2"}, clear=True),
            patch.object(ops, "load_env"),
            patch.object(ops, "compose", side_effect=compose),
            patch.object(ops, "drain") as drain,
            patch("sys.argv", ["manage.py", "config-apply"]),
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                ops.main()
            drain.assert_not_called()

    def test_config_apply_refreshes_proxy_after_recreating_api(self):
        with (
            patch.dict(os.environ, {"VERSION": "v2"}, clear=True),
            patch.object(ops, "load_env"),
            patch.object(ops, "config_check"),
            patch.object(ops, "compose") as compose,
            patch.object(ops, "drain"),
            patch.object(ops, "business"),
            patch("sys.argv", ["manage.py", "config-apply"]),
        ):
            ops.main()
            compose.assert_any_call(
                "up", "-d", "--force-recreate", "--wait", "api", "algorithm", "algorithm-worker", "web"
            )

    def test_make_exported_empty_local_build_still_builds(self):
        with (
            patch.dict(os.environ, {"VERSION": "v2", "LOCAL_BUILD": ""}, clear=True),
            patch.object(ops, "load_env"),
            patch.object(ops, "deploy") as deploy,
            patch("sys.argv", ["manage.py", "deploy"]),
        ):
            ops.main()
            self.assertTrue(deploy.call_args.kwargs["build"])
            self.assertFalse(deploy.call_args.kwargs["pull"])

    def test_rollback_reuses_recorded_version_without_build_or_pull(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            (runtime / "previous-version").write_text("v1\n")
            with (
                patch.object(ops, "RUNTIME", runtime),
                patch.dict(os.environ, {}, clear=True),
                patch.object(ops, "load_env"),
                patch.object(ops, "deploy") as deploy,
                patch("sys.argv", ["manage.py", "rollback"]),
            ):
                ops.main()
            deploy.assert_called_once_with("v1", build=False, pull=False)

    def test_restore_rejects_incomplete_backup_before_drain(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "database.dump").write_bytes(b"archive")
            with (
                patch.dict(os.environ, {"BACKUP": str(source)}, clear=True),
                patch.object(ops, "drain") as drain,
            ):
                with self.assertRaisesRegex(RuntimeError, "Backup is incomplete"):
                    ops.restore()
                drain.assert_not_called()

    def test_dev_deploy_preserves_production_version(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            (runtime / "current-version").write_text("production-v1\n")
            with (
                patch.object(ops, "RUNTIME", runtime),
                patch.dict(os.environ, {"RALLYMARK_MODE": "dev"}, clear=True),
                patch.object(ops, "compose", return_value=""),
                patch.object(ops, "drain"),
                patch.object(ops, "migrate"),
                patch.object(ops, "business"),
                patch.object(ops, "prepare_weights") as prepare,
            ):
                ops.deploy("local", build=True)
                prepare.assert_not_called()
            self.assertEqual(
                (runtime / "current-version").read_text(), "production-v1\n"
            )
            self.assertEqual((runtime / "dev/current-version").read_text(), "local\n")

    def test_restore_database_is_atomic(self):
        self.restore_case()

    def test_migration_can_restore_with_a_compatible_application(self):
        self.restore_case("v2")

    def restore_case(self, override=""):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "backup"
            source.mkdir()
            (source / "database.dump").write_bytes(b"archive")
            (source / "config.yaml").write_text("algorithm: {}\n")
            (source / "version").write_text("v1\n")
            (source / "deploy.env").write_text(
                "POSTGRES_PASSWORD=p\nBUSINESS_DB_PASSWORD=b\nALGORITHM_DB_PASSWORD=a\n"
            )
            config = root / "configured.yaml"
            runtime = root / "runtime"
            runtime.mkdir()

            def compose(*args, **kwargs):
                if args[:2] == ("config", "--format"):
                    return json.dumps(
                        {
                            "services": {
                                name: {"image": name + ":" + os.environ["VERSION"]}
                                for name in (
                                    "api",
                                    "algorithm",
                                    "algorithm-worker",
                                    "web",
                                )
                            }
                        }
                    )
                return "container-id"

            with (
                patch.dict(
                    os.environ,
                    {
                        "BACKUP": str(source),
                        "VERSION": "v2",
                        "RESTORE_VERSION": override,
                        "POSTGRES_PASSWORD": "p",
                        "BUSINESS_DB_PASSWORD": "b",
                        "ALGORITHM_DB_PASSWORD": "a",
                    },
                    clear=True,
                ),
                patch.object(ops, "RUNTIME", runtime),
                patch.object(ops, "configured_path", return_value=config),
                patch.object(ops, "compose", side_effect=compose),
                patch.object(ops, "run") as run,
                patch.object(ops, "drain"),
                patch.object(ops, "business"),
            ):
                ops.restore()
            restore_command = next(
                call.args[0]
                for call in run.call_args_list
                if "pg_restore" in call.args[0]
            )
            self.assertIn("--single-transaction", restore_command)
            self.assertEqual(config.read_text(), "algorithm: {}\n")
            self.assertEqual(
                (runtime / "current-version").read_text().strip(), override or "v1"
            )
            self.assertEqual((source / "version").read_text(), "v1\n")
            provenance = json.loads((runtime / "last-restore.json").read_text())
            self.assertEqual(provenance["backup_version"], "v1")
            self.assertEqual(provenance["application_version"], override or "v1")


class DeploymentTargets(unittest.TestCase):
    def test_remote_operations_use_selected_host_and_directory(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(ops, "RUNTIME", Path(directory)),
            patch.dict(
                os.environ,
                {
                    "DEPLOY_HOST": "bigstrong",
                    "DEPLOY_DIR": "projects/rallymark",
                    "VERSION": "123abcd",
                },
                clear=True,
            ),
            patch.object(ops, "run") as run,
        ):
            self.assertTrue(ops.forward_remote("deploy"))
            command = run.call_args.args[0]
            self.assertEqual(command[:3], ["ssh", "--", "bigstrong"])
            self.assertIn("projects/rallymark", command[-1])
            self.assertIn("RALLYMARK_LOCAL=1", command[-1])
            self.assertIn("VERSION=123abcd", command[-1])

    def test_remote_child_does_not_forward_again(self):
        with (
            patch.dict(
                os.environ,
                {"DEPLOY_HOST": "bigstrong", "RALLYMARK_LOCAL": "1"},
                clear=True,
            ),
            patch.object(ops, "run") as run,
        ):
            self.assertFalse(ops.forward_remote("deploy"))
            run.assert_not_called()

    def test_remote_paths_cannot_escape_deployment_home(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(ops, "RUNTIME", Path(directory)),
            patch.dict(
                os.environ,
                {"DEPLOY_HOST": "bigstrong", "DEPLOY_DIR": "../data"},
                clear=True,
            ),
            patch.object(ops, "run") as run,
        ):
            with self.assertRaises(ValueError):
                ops.forward_remote("data-clean")
            run.assert_not_called()

    def test_saved_target_can_be_overridden_without_editing_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "target.env").write_text(
                "DEPLOY_HOST=old-host\nDEPLOY_DIR=projects/rallymark\n"
            )
            with (
                patch.object(ops, "RUNTIME", root),
                patch.dict(os.environ, {"DEPLOY_HOST": "new-host"}, clear=True),
                patch.object(ops, "run") as run,
            ):
                self.assertTrue(ops.forward_remote("status"))
                self.assertEqual(run.call_args.args[0][2], "new-host")


class GpuPreflight(unittest.TestCase):
    def test_busy_current_job_can_reach_deployment_drain(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(ops, "RUNTIME", Path(directory)),
            patch.dict(os.environ, {"GPU_DEVICE": "0"}, clear=True),
            patch.object(
                ops, "run", return_value="RTX 4080, GPU-example, 16376, 4096\n"
            ),
            patch.object(ops, "compose", return_value=""),
            patch.object(ops, "prepare_weights"),
            patch.object(ops, "drain") as drain,
            patch.object(ops, "migrate"),
            patch.object(ops, "business"),
        ):
            ops.deploy("portable", build=True)
            drain.assert_called_once()

    def test_selected_uuid_is_checked(self):
        with (
            patch.dict(
                os.environ,
                {"GPU_DEVICE": "GPU-aabb", "MIN_GPU_MEMORY_GIB": "12"},
                clear=True,
            ),
            patch.object(
                ops, "run", return_value="RTX 4080, GPU-aabb, 16376, 15360\n"
            ) as run,
        ):
            ops.gpu_preflight()
            self.assertIn("--id=GPU-aabb", run.call_args.args[0])

    def test_busy_gpu_fails_before_deployment(self):
        with (
            patch.dict(os.environ, {"GPU_DEVICE": "0"}, clear=True),
            patch.object(
                ops, "run", return_value="RTX 4080, GPU-example, 16376, 4096\n"
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "free"):
                ops.gpu_preflight()

    def test_fake_development_needs_no_gpu(self):
        with (
            patch.dict(os.environ, {"RALLYMARK_MODE": "dev"}, clear=True),
            patch.object(ops, "run") as run,
        ):
            ops.gpu_preflight()
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
