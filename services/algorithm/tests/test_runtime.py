from types import SimpleNamespace

import pytest

from rallymark_algorithm.runtime import validate_gpu


def cuda(name="NVIDIA GeForce RTX 4080", total=16, free=15, available=True):
    return SimpleNamespace(
        is_available=lambda: available,
        get_device_properties=lambda _: SimpleNamespace(name=name, total_memory=total * 2**30),
        mem_get_info=lambda _: (free * 2**30, total * 2**30),
    )


def test_gpu_admission_uses_capacity_not_model_name():
    info = validate_gpu(cuda(), 12)
    assert info["gpu_name"] == "NVIDIA GeForce RTX 4080"
    assert info["gpu_memory_gib"] == 16


@pytest.mark.parametrize(
    ("device", "message"),
    [(cuda(available=False), "CUDA"), (cuda(total=8, free=7), "total"), (cuda(free=4), "free")],
)
def test_gpu_admission_rejects_unusable_device(device, message):
    with pytest.raises(RuntimeError, match=message):
        validate_gpu(device, 12)
