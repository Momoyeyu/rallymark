import pytest

from rallymark_algorithm.gpu_pool import Device, choose_devices, lock_key, parse_devices


def gpu(index, *, free=30000, utilization=0, foreign=0):
    return Device(
        index=str(index),
        uuid=f"GPU-{index}",
        name="GPU",
        total_mib=32760,
        free_mib=free,
        utilization=utilization,
        compute_mib=foreign,
    )


def test_admission_excludes_foreign_load_low_memory_and_reserved_cards():
    rows = [gpu(0, foreign=1000), gpu(1, free=4000), gpu(2, utilization=90), gpu(3)]
    assert [d.index for d in choose_devices(rows, set(), 4, 1, 14, 20)] == ["3"]
    assert choose_devices(rows, {"GPU-3"}, 4, 1, 14, 20) == []


def test_single_job_uses_spare_cards_but_backlog_shares_them():
    rows = [gpu(i) for i in range(4)]
    assert len(choose_devices(rows, set(), 4, 1, 14, 20)) == 4
    assert len(choose_devices(rows, set(), 4, 2, 14, 20)) == 2
    assert len(choose_devices(rows, set(), 4, 8, 14, 20)) == 1
    assert len(choose_devices(rows, {"GPU-1", "GPU-2", "GPU-3"}, 4, 8, 14, 20)) == 1


def test_stable_uuid_lock_does_not_depend_on_local_index():
    assert lock_key("GPU-1") == lock_key("GPU-1")
    assert lock_key("GPU-1") != lock_key("GPU-2")
    assert -(2**63) <= lock_key("GPU-1") < 2**63


def test_telemetry_fails_closed_and_allowlist_is_enforced():
    text = "0, GPU-a, RTX 4080 SUPER, 32760, 30000, 18, 0\n1, GPU-b, RTX 4080 SUPER, 32760, 30000, 18, 1\n"
    rows = parse_devices(text, "GPU-b", {"GPU-b": 1000})
    assert len(rows) == 1 and rows[0].index == "1" and rows[0].compute_mib == 1000
    assert len(parse_devices(text, "0", {})) == 1
    for broken in ["0, GPU-a, GPU, 32760, N/A, 18, 0", "0, GPU-a, GPU, 32760, 30000, 18, -1"]:
        with pytest.raises(ValueError):
            parse_devices(broken, "all", {})
    with pytest.raises(ValueError):
        parse_devices(text, "4", {})


def test_auto_capacity_handles_one_three_and_eight_cards_without_a_fixed_four_card_cap():
    for count in [1, 3, 8]:
        devices = [gpu(i) for i in range(count)]
        assert len(choose_devices(devices, set(), 0, 1, 14, 20)) == count
        assert len(choose_devices(devices, set(), 0, count, 14, 20)) == 1


def test_resource_policy_is_algorithm_only_and_auto_by_default():
    from rallymark_algorithm.settings import GpuPoolConfig

    assert GpuPoolConfig().max_gpus_per_job == 0
    assert GpuPoolConfig().max_concurrent_jobs == 0


def test_host_allocations_are_detected_when_container_cannot_see_foreign_pids():
    # NVML process enumeration can be empty in a private PID namespace.
    row = "0, GPU-a, RTX 4080, 32760, 24000, 8500, 0\n"
    devices = parse_devices(row, "all", {})
    assert devices[0].used_mib == 8500
    assert choose_devices(devices, set(), 0, 1, 14, 20) == []
