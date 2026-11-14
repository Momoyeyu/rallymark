"""Contiguous partitions of global windows, without cutting or re-encoding video."""


def select_windows(windows, index, count):
    if not 1 <= count <= len(windows) or not 0 <= index < count:
        raise ValueError(
            "Partition must be nonempty and belong to the global window set"
        )
    return windows[len(windows) * index // count : len(windows) * (index + 1) // count]
