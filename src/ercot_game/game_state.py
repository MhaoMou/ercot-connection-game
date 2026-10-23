"""Round sequencing and persistence boundary for the classroom game.

A state follows the released schedule of three weeks x two submissions
(``week-N-submission-M`` round keys).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Iterable, Mapping

from .asset_state import AssetLedger
from .calendars import ROUND_SEQUENCE, weekly_match_for
from .models import TeamPlan


class RoundTransitionError(ValueError):
    """Raised when a game state transition is invalid."""


RELEASED_ROUND_SEQUENCE = ROUND_SEQUENCE
# The only schedule; older state files may record it as ``schedule_id``.
SCHEDULE_ID = "representative"


@dataclass(frozen=True)
class GameState:
    """Immutable state for three two-submission weekly classroom matches.

    ``carried_base_load_mw_by_bus`` holds the hourly net grid withdrawal of
    the current week's Submission 1 sites; it becomes base load in Submission 2 and is cleared at the next week.
    """

    state_version: int = 1
    current_round_key: str | None = None
    completed_rounds: tuple[str, ...] = ()
    asset_ledger: AssetLedger = field(default_factory=AssetLedger.empty)
    carried_base_load_mw_by_bus: Mapping[str, tuple[float, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        completed = tuple(self.completed_rounds)
        object.__setattr__(self, "completed_rounds", completed)
        if self.state_version != 1:
            raise RoundTransitionError(
                f"unsupported game-state version: {self.state_version!r}"
            )
        if completed != self.round_sequence[: len(completed)]:
            raise RoundTransitionError("completed rounds must form a contiguous released prefix")
        carried = {}
        for bus_id, values in dict(self.carried_base_load_mw_by_bus).items():
            series = tuple(float(value) for value in values)
            if not isinstance(bus_id, str) or any(not math.isfinite(value) for value in series):
                raise RoundTransitionError("carried base load must map bus IDs to finite values")
            carried[bus_id] = series
        object.__setattr__(self, "carried_base_load_mw_by_bus", carried)
        expected_current = completed[-1] if completed else None
        if self.current_round_key != expected_current:
            raise RoundTransitionError(
                "current_round_key must equal the last completed round"
            )

    @classmethod
    def new(cls) -> "GameState":
        return cls()

    @property
    def round_sequence(self) -> tuple[str, ...]:
        """Round keys of the released schedule in play order."""
        return RELEASED_ROUND_SEQUENCE

    @property
    def next_round_key(self) -> str | None:
        next_index = len(self.completed_rounds)
        if next_index >= len(self.round_sequence):
            return None
        return self.round_sequence[next_index]

    @property
    def current_week_id(self) -> str | None:
        """The weekly match containing the current round, if any."""
        if self.current_round_key is None:
            return None
        return weekly_match_for(self.current_round_key).week_id

    @property
    def current_submission_number(self) -> int | None:
        """The one-based submission number within the current weekly match."""
        if self.current_round_key is None:
            return None
        match = weekly_match_for(self.current_round_key)
        return match.round_keys.index(self.current_round_key) + 1

    @property
    def current_feedback_only(self) -> bool | None:
        """Whether the current submission belongs to the unranked practice week."""
        if self.current_round_key is None:
            return None
        return weekly_match_for(self.current_round_key).feedback_only

    @property
    def next_week_id(self) -> str | None:
        """The weekly match containing the next round, if any."""
        if self.next_round_key is None:
            return None
        return weekly_match_for(self.next_round_key).week_id

    @property
    def next_submission_number(self) -> int | None:
        """The one-based submission number expected next."""
        if self.next_round_key is None:
            return None
        match = weekly_match_for(self.next_round_key)
        return match.round_keys.index(self.next_round_key) + 1

    @property
    def next_feedback_only(self) -> bool | None:
        """Whether the next submission belongs to the unranked practice week."""
        if self.next_round_key is None:
            return None
        return weekly_match_for(self.next_round_key).feedback_only

    def advance(self, round_key: str, plans: Iterable[TeamPlan]) -> "GameState":
        """Commit one submission's team plans and advance exactly one round."""
        _validate_round_key(round_key)
        sequence = RELEASED_ROUND_SEQUENCE
        index = len(self.completed_rounds)
        expected = sequence[index] if index < len(sequence) else None
        if expected is None:
            raise RoundTransitionError("the released three-week game is already complete")
        if round_key != expected:
            raise RoundTransitionError(
                f"round transition expected {expected}, received {round_key}"
            )

        plan_tuple = tuple(plans)
        team_ids = [plan.team_id for plan in plan_tuple]
        if any(not team_id for team_id in team_ids):
            raise RoundTransitionError("every plan must have a non-empty team_id")
        if len(set(team_ids)) != len(team_ids):
            raise RoundTransitionError("at most one plan per team is allowed in a round")

        next_match = weekly_match_for(round_key)
        ledger = self.asset_ledger
        carried = self.carried_base_load_mw_by_bus
        if self.current_week_id != next_match.week_id:
            ledger = ledger.reset()
            carried = {}
        for plan in plan_tuple:
            ledger = ledger.register_plan(plan, round_key=round_key)
        completed = self.completed_rounds + (round_key,)
        return GameState(
            state_version=self.state_version,
            current_round_key=round_key,
            completed_rounds=completed,
            asset_ledger=ledger,
            carried_base_load_mw_by_bus=carried,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "state_version": self.state_version,
            "current_round_key": self.current_round_key,
            "current_week_id": self.current_week_id,
            "current_submission_number": self.current_submission_number,
            "current_feedback_only": self.current_feedback_only,
            "completed_rounds": list(self.completed_rounds),
            "asset_ledger": self.asset_ledger.to_dict(),
        }
        if self.carried_base_load_mw_by_bus:
            payload["carried_base_load_mw_by_bus"] = {
                bus_id: list(values)
                for bus_id, values in sorted(self.carried_base_load_mw_by_bus.items())
            }
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GameState":
        if not isinstance(payload, Mapping):
            raise RoundTransitionError("game state must be an object")
        completed = payload.get("completed_rounds", ())
        if not isinstance(completed, (list, tuple)):
            raise RoundTransitionError("completed_rounds must be an array")
        ledger_payload = payload.get("asset_ledger")
        if not isinstance(ledger_payload, Mapping):
            raise RoundTransitionError("asset_ledger must be an object")
        if payload.get("schedule_id", SCHEDULE_ID) != SCHEDULE_ID:
            raise RoundTransitionError(f"unknown classroom schedule: {payload.get('schedule_id')!r}")
        carried = payload.get("carried_base_load_mw_by_bus", {})
        if not isinstance(carried, Mapping):
            raise RoundTransitionError("carried_base_load_mw_by_bus must be an object")
        state = cls(
            state_version=payload.get("state_version"),
            current_round_key=payload.get("current_round_key"),
            completed_rounds=tuple(completed),
            asset_ledger=AssetLedger.from_dict(ledger_payload),
            carried_base_load_mw_by_bus=carried,
        )
        serialized_metadata = {
            "current_week_id": state.current_week_id,
            "current_submission_number": state.current_submission_number,
            "current_feedback_only": state.current_feedback_only,
        }
        for field_name, expected in serialized_metadata.items():
            if field_name in payload and payload[field_name] != expected:
                raise RoundTransitionError(
                    f"{field_name} does not match current_round_key"
                )
        return state


def _validate_round_key(round_key: str) -> None:
    if not isinstance(round_key, str) or round_key not in RELEASED_ROUND_SEQUENCE:
        raise RoundTransitionError(
            "round_key must identify a released submission (week-N-submission-M)"
        )
