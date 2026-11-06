"""Shared interpretation of the pinned PowerVR DDK's module version formats."""
import re

EXPECTED_DDK='24.2.6603887'
# pvrversion.h exposes build 6603887 as BUILD_HI=660 and BUILD_LO=3887.
PATTERN=re.compile(r'(?<![\d.])24\.2(?:[.@]6603887|\.660\.3887)(?![\d.])')


def canonical_ddk(value):
    """Return the exact supported DDK, or None; unrelated versions never pass."""
    return EXPECTED_DDK if PATTERN.search(value.strip()) else None
