import importlib.util
import json
import os
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
            ):
                ops.deploy("local", build=True)
            self.assertEqual(
                (runtime / "current-version").read_text(), "production-v1\n"
            )
            self.assertEqual((runtime / "dev/current-version").read_text(), "local\n")

    def test_restore_database_is_atomic(self):
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
                                name: {"image": name + ":v1"}
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


if __name__ == "__main__":
    unittest.main()
