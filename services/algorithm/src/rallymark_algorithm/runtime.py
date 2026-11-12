def validate_gpu(cuda, minimum_gib):
    if not cuda.is_available():
        raise RuntimeError("CUDA is unavailable on the assigned GPU")
    properties = cuda.get_device_properties(0)
    free_bytes, _ = cuda.mem_get_info(0)
    total_gib = properties.total_memory / 2**30
    free_gib = free_bytes / 2**30
    if total_gib < minimum_gib:
        raise RuntimeError(f"Assigned GPU total memory {total_gib:.1f} GiB is below {minimum_gib:g} GiB")
    if free_gib < minimum_gib:
        raise RuntimeError(f"Assigned GPU free memory {free_gib:.1f} GiB is below {minimum_gib:g} GiB")
    return {"gpu_name": properties.name, "gpu_memory_gib": total_gib, "gpu_free_gib": free_gib}
