"""Immutable image capability, independent of runtime creation flags.

Docker builds stamp this constant before dropping privileges. The supported
bridge shares all readers/management code but cannot create independent entries.
An environment override is deliberately not an authority for this build role.
"""
BUILD_ROLE = 'candidate'


def creation_allowed():
    if BUILD_ROLE not in {'candidate', 'bridge'}:
        raise ValueError('unknown_entry_discovery_build_role')
    return BUILD_ROLE == 'candidate'


def capabilities():
    return dict(build_role=BUILD_ROLE, independent_creation=creation_allowed(),
                snapshot_formats=list(range(1, 9)), audit_version='entry_discovery_v1',
                execution_version='independent_entry_execution_v1')
