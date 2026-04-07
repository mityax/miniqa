from miniqa.lib.test_case.test_case_file import TestCase


def resolve_test_case_dependency_chain(target: TestCase, all_tests: list[TestCase]):
    """
    Resolves the given [target] [TestCase]'s dependencies and returns them in order (i.e. the first
    [TestCase] in the returned list must be run first).

    :param target: The [TestCase] to resolve the dependency chain of.
    :param all_tests: All existing [TestCase]s to pick the dependencies from.

    :raises AmbiguousSnapshotError: If a dependency can be resolved by more than one test case
    :raises UnmetDependencyError: If a dependency is missing in [all_tests]
    :raises CircularDependencyError: If a circular dependency is detected
    """

    current = target
    visited = set()
    chain = []

    while current.from_:
        dep_candidates = tuple(tc for tc in all_tests if current.from_ in tc.snapshots)

        if not dep_candidates:
            raise UnmetDependencyError(f"Snapshot {current.from_} (required by {current.name}) is not created by any test case")
        elif len(dep_candidates) > 1:
            raise AmbiguousSnapshotError(f"Snapshot {current.from_} is provided by more than one test case: {', '.join(tc.name for tc in dep_candidates)}")

        dep = dep_candidates[0]

        if dep in visited:
            raise CircularDependencyError(f"Circular test case dependency: {target.name} -> {' -> '.join(tc.name for tc in reversed(chain))}")

        chain.insert(0, dep)
        visited.add(dep)
        current = dep

    return chain


class CircularDependencyError(ValueError):
    pass

class UnmetDependencyError(ValueError):
    pass

class AmbiguousSnapshotError(ValueError):
    pass
