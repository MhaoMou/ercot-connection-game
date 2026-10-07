"""Immutable domain objects for the offline evaluator."""

from dataclasses import InitVar, dataclass, field
from collections.abc import Mapping, Sequence
from copy import deepcopy
from types import MappingProxyType


_UNSET = object()


class _ImmutableList(list):
    """List-compatible container that rejects every mutation operation."""

    def _immutable(self, *args: object, **kwargs: object) -> None:
        raise TypeError("immutable metadata")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable


class _ImmutableDict(dict):
    """Dict-compatible container that rejects every mutation operation."""

    def _immutable(self, *args: object, **kwargs: object) -> None:
        raise TypeError("immutable result")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __ior__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable


def _freeze_presentation(value: object) -> object:
    """Recursively copy presentation data into immutable containers."""
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_presentation(item) for key, item in value.items()}
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_presentation(item) for item in value)
    return deepcopy(value)


def _freeze_metadata(value: object) -> object:
    """Recursively copy metadata while preserving list-compatible equality."""
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_metadata(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return _ImmutableList(_freeze_metadata(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_metadata(item) for item in value)
    return deepcopy(value)


def _freeze_result(value: object) -> object:
    """Recursively detach result data while retaining JSON-friendly containers."""
    if isinstance(value, Mapping):
        return _ImmutableDict(
            {key: _freeze_result(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return _ImmutableList(_freeze_result(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_result(item) for item in value)
    return deepcopy(value)


@dataclass(frozen=True)
class ConnectionPlan:
    """Canonical connection data with deterministic corridor ordering."""

    connection_id: str
    bus_id: str
    path_corridors: tuple[str, ...]
    capacity_mw: float
    profile: tuple[float, ...]

    def __post_init__(self) -> None:
        # Corridor order is not semantic to the current evaluator.  Normalize
        # valid string IDs at construction so model and serialized round trips
        # agree.  Preserve malformed mixed-type order for stable diagnostics.
        path_corridors = tuple(self.path_corridors)
        if all(isinstance(corridor_id, str) for corridor_id in path_corridors):
            path_corridors = tuple(sorted(path_corridors))
        object.__setattr__(
            self, "path_corridors", path_corridors
        )
        object.__setattr__(self, "profile", tuple(self.profile))


@dataclass(frozen=True, init=False)
class GeneratorPlan:
    generator_id: str
    connection_id: str
    capacity_mw: float
    marginal_cost_per_mwh: float

    def __init__(
        self,
        generator_id: str,
        connection_id: str | float = "connection-legacy",
        capacity_mw: float | None = None,
        marginal_cost_per_mwh: float | None = None,
    ) -> None:
        """Create a site-attached generator, accepting the old 3-argument form."""
        if marginal_cost_per_mwh is None:
            if capacity_mw is None:
                raise TypeError("marginal_cost_per_mwh is required")
            legacy_capacity = connection_id
            connection_id = "connection-legacy"
            marginal_cost_per_mwh = capacity_mw
            capacity_mw = legacy_capacity  # type: ignore[assignment]
        elif not isinstance(connection_id, str):
            raise TypeError("connection_id must be a string")
        if capacity_mw is None:
            raise TypeError("capacity_mw is required")
        object.__setattr__(self, "generator_id", generator_id)
        object.__setattr__(self, "connection_id", str(connection_id))
        object.__setattr__(self, "capacity_mw", capacity_mw)
        object.__setattr__(self, "marginal_cost_per_mwh", marginal_cost_per_mwh)


@dataclass(frozen=True)
class StoragePlan:
    """Team-owned storage attached to one connection site."""

    storage_id: str
    connection_id: str
    power_mw: float
    energy_mwh: float


@dataclass(frozen=True, init=False)
class TeamPlan:
    team_id: str
    connections: tuple[ConnectionPlan, ...]
    generators: tuple[GeneratorPlan, ...]
    storages: tuple[StoragePlan, ...]
    intervention_budget_k: int
    curtailment_depth_mu: float
    flexibility_fee_per_mwh: float

    # These fields are deliberately retained as a dataclass-compatible migration
    # view.  Existing evaluator code and dataclasses.replace() callers still use
    # the single-site names until the multi-site evaluator task lands.
    bus_id: str | None = field(default=None, compare=False)
    path_corridors: tuple[str, ...] = field(default=(), compare=False)
    capacity_mw: float = field(default=0.0, compare=False)
    profile: tuple[float, ...] = field(default=(), compare=False)
    generator: GeneratorPlan | None = field(default=None, compare=False)
    _compat_source: InitVar[tuple[
        tuple[ConnectionPlan, ...], tuple[GeneratorPlan, ...]
    ] | object] = _UNSET

    def __init__(
        self,
        team_id: str,
        *args: object,
        connections: tuple[ConnectionPlan, ...] | None = None,
        generators: tuple[GeneratorPlan, ...] | None = None,
        storages: tuple[StoragePlan, ...] | None = None,
        intervention_budget_k: int = 0,
        curtailment_depth_mu: float = 0.0,
        flexibility_fee_per_mwh: float = 0.0,
        bus_id: str | None | object = _UNSET,
        path_corridors: tuple[str, ...] | object = _UNSET,
        capacity_mw: float | object = _UNSET,
        profile: tuple[float, ...] | object = _UNSET,
        generator: GeneratorPlan | None | object = _UNSET,
        _compat_source: tuple[
            tuple[ConnectionPlan, ...], tuple[GeneratorPlan, ...]
        ] | object = _UNSET,
    ) -> None:
        """Create a canonical plan, while accepting the legacy single-site form."""
        if args:
            if len(args) == 5:
                if connections is not None or generators is not None or storages is not None:
                    raise TypeError("canonical plan fields supplied twice")
                connections, generators, intervention_budget_k, curtailment_depth_mu, flexibility_fee_per_mwh = args  # type: ignore[assignment]
            elif len(args) == 8:
                if connections is not None or generators is not None or storages is not None:
                    raise TypeError("canonical and legacy plan fields cannot be mixed")
                (
                    bus_id,
                    path_corridors,
                    capacity_mw,
                    profile,
                    generator,
                    intervention_budget_k,
                    curtailment_depth_mu,
                    flexibility_fee_per_mwh,
                ) = args  # type: ignore[assignment]
                connections = None
                generators = None
            else:
                raise TypeError("TeamPlan expects canonical or legacy positional fields")

        legacy_fields_present = any(
            value is not _UNSET
            for value in (bus_id, path_corridors, capacity_mw, profile, generator)
        )
        legacy_bus_id = None if bus_id is _UNSET else bus_id
        legacy_path_corridors = () if path_corridors is _UNSET else path_corridors
        legacy_capacity_mw = 0.0 if capacity_mw is _UNSET else capacity_mw
        legacy_profile = () if profile is _UNSET else profile
        legacy_generator = None if generator is _UNSET else generator

        compatibility_source = (
            None if _compat_source is _UNSET else _compat_source
        )
        legacy_mode = connections is None and generators is None
        if legacy_mode:
            connection = ConnectionPlan(
                "connection-legacy",
                legacy_bus_id,  # type: ignore[arg-type]
                legacy_path_corridors,  # type: ignore[arg-type]
                legacy_capacity_mw,  # type: ignore[arg-type]
                legacy_profile,  # type: ignore[arg-type]
            )
            canonical_connections = (connection,)
            canonical_generators = (
                (legacy_generator,) if legacy_generator is not None else ()
            )
            canonical_storages: tuple[StoragePlan, ...] = ()
        else:
            canonical_connections = tuple(connections or ())
            canonical_generators = tuple(generators or ())
            canonical_storages = tuple(storages or ())
            canonical_fields_replaced = compatibility_source is not None and (
                canonical_connections != compatibility_source[0]
                or canonical_generators != compatibility_source[1]
            )
            if legacy_fields_present and compatibility_source is None:
                expected_connection = (
                    canonical_connections[0]
                    if len(canonical_connections) == 1
                    else None
                )
                expected_generator = (
                    canonical_generators[0]
                    if len(canonical_generators) == 1
                    else None
                )
                direct_legacy_matches = (
                    (bus_id is _UNSET or bus_id == (expected_connection.bus_id if expected_connection else None))
                    and (
                        path_corridors is _UNSET
                        or tuple(path_corridors) == (
                            expected_connection.path_corridors
                            if expected_connection
                            else ()
                        )
                    )
                    and (
                        capacity_mw is _UNSET
                        or capacity_mw == (
                            expected_connection.capacity_mw
                            if expected_connection
                            else 0.0
                        )
                    )
                    and (
                        profile is _UNSET
                        or tuple(profile)
                        == (expected_connection.profile if expected_connection else ())
                    )
                    and (
                        generator is _UNSET or generator == expected_generator
                    )
                )
                if not direct_legacy_matches:
                    raise ValueError(
                        "canonical and legacy TeamPlan fields must agree"
                    )
            if (
                len(canonical_connections) == 1
                and legacy_fields_present
                and compatibility_source is not None
                and not canonical_fields_replaced
            ):
                current = canonical_connections[0]
                legacy_connection_changed = (
                    legacy_bus_id is not None
                    and legacy_bus_id != current.bus_id
                ) or (
                    tuple(legacy_path_corridors) != current.path_corridors
                    or legacy_capacity_mw != current.capacity_mw
                    or tuple(legacy_profile) != current.profile
                )
                if legacy_connection_changed:
                    canonical_connections = (
                        ConnectionPlan(
                            current.connection_id,
                            legacy_bus_id,
                            legacy_path_corridors,
                            legacy_capacity_mw,
                            legacy_profile,
                        ),
                    )
            if (
                legacy_fields_present
                and len(canonical_generators) == 1
                and compatibility_source is not None
                and not canonical_fields_replaced
            ):
                current_generator = canonical_generators[0]
                if legacy_generator != current_generator:
                    canonical_generators = (
                        (legacy_generator,) if legacy_generator is not None else ()
                    )
            elif (
                legacy_fields_present
                and not canonical_generators
                and legacy_generator is not None
                and compatibility_source is not None
                and not canonical_fields_replaced
            ):
                canonical_generators = (legacy_generator,)

        object.__setattr__(self, "team_id", team_id)
        object.__setattr__(self, "connections", tuple(canonical_connections))
        object.__setattr__(self, "generators", tuple(canonical_generators))
        object.__setattr__(self, "storages", tuple(canonical_storages))
        object.__setattr__(self, "intervention_budget_k", intervention_budget_k)
        object.__setattr__(self, "curtailment_depth_mu", curtailment_depth_mu)
        object.__setattr__(self, "flexibility_fee_per_mwh", flexibility_fee_per_mwh)

        if len(canonical_connections) == 1:
            connection = canonical_connections[0]
            compatibility_generator = (
                canonical_generators[0] if len(canonical_generators) == 1 else None
            )
            object.__setattr__(self, "bus_id", connection.bus_id)
            object.__setattr__(self, "path_corridors", connection.path_corridors)
            object.__setattr__(self, "capacity_mw", connection.capacity_mw)
            object.__setattr__(self, "profile", connection.profile)
            object.__setattr__(self, "generator", compatibility_generator)
        else:
            object.__setattr__(self, "bus_id", None)
            object.__setattr__(self, "path_corridors", ())
            object.__setattr__(self, "capacity_mw", 0.0)
            object.__setattr__(self, "profile", ())
            object.__setattr__(self, "generator", None)
        object.__setattr__(
            self,
            "_compat_source",
            (tuple(canonical_connections), tuple(canonical_generators)),
        )


@dataclass(frozen=True)
class Bus:
    bus_id: str
    headroom_mw_by_time: tuple[float, ...]
    presentation: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "headroom_mw_by_time", tuple(self.headroom_mw_by_time))
        object.__setattr__(self, "presentation", _freeze_presentation(self.presentation))


@dataclass(frozen=True)
class Corridor:
    corridor_id: str
    capacity_mw_by_time: tuple[float, ...]
    presentation: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "capacity_mw_by_time", tuple(self.capacity_mw_by_time)
        )
        object.__setattr__(self, "presentation", _freeze_presentation(self.presentation))


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    evaluator_version: str
    buses: tuple[Bus, ...]
    corridors: tuple[Corridor, ...]
    energy_price_per_mwh: tuple[float, ...]
    it_value_per_mwh: tuple[float, ...]
    time_step_hours: float
    metadata: Mapping[str, object] = field(default_factory=dict)
    base_load_mw_by_time: tuple[float, ...] = ()
    presentation: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "buses", tuple(self.buses))
        object.__setattr__(self, "corridors", tuple(self.corridors))
        object.__setattr__(
            self, "energy_price_per_mwh", tuple(self.energy_price_per_mwh)
        )
        object.__setattr__(self, "it_value_per_mwh", tuple(self.it_value_per_mwh))
        object.__setattr__(
            self, "base_load_mw_by_time", tuple(self.base_load_mw_by_time)
        )
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))
        object.__setattr__(self, "presentation", _freeze_presentation(self.presentation))


@dataclass(frozen=True)
class EvaluationConfig:
    curtailment_cost_per_mwh: float
    unserved_penalty_per_mwh: float
    emergency_energy_cost_per_mwh: float


@dataclass(frozen=True)
class EvaluationResult:
    scenario_id: str
    input_hash: str
    team_results: tuple[dict[str, object], ...]
    aggregate_diagnostics: dict[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "team_results",
            tuple(_freeze_result(team) for team in self.team_results),
        )
        object.__setattr__(
            self,
            "aggregate_diagnostics",
            _freeze_result(self.aggregate_diagnostics),
        )
