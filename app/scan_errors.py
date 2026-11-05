"""Scan lifecycle errors shared by scanner and Azure collectors."""


class ScanError(RuntimeError):
    """The scan could not produce a complete, authorized result."""
