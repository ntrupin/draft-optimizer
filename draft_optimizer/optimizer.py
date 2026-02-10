from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import random
from typing import Dict, List, Sequence, Tuple

from .models import DraftState, Player

try:
    import torch
except Exception:
    torch = None


@dataclass(slots=True)
class Recommendation:
    player_id: str
    name: str
    positions: Tuple[str, ...]
    projected_points: float
    score: float
    suggested_slot: str
    replacement_at_next_pick: float
    scarcity_dropoff: float
    feasible: bool
    rationale: str


class DraftOptimizer:
    def __init__(
        self,
        state: DraftState,
        bench_discount_when_needs_open: float = 0.28,
        bench_discount_when_active_full: float = 0.72,
        scarcity_weight: float = 0.35,
        use_monte_carlo_replacement: bool = True,
        monte_carlo_trials: int = 220,
        monte_carlo_seed: int = 17,
        opponent_candidate_pool: int = 75,
        opponent_temperature: float = 16.0,
        opponent_need_bonus: float = 22.0,
        opponent_scarcity_weight: float = 0.22,
        opponent_bench_discount_when_needs_open: float = 0.84,
        opponent_bench_discount_when_active_full: float = 0.96,
    ) -> None:
        self.state = state
        self.slots = self.state.roster_config.expanded_active_slots
        self.unique_slots = tuple(self.state.roster_config.active_slots.keys())
        self.bench_discount_when_needs_open = bench_discount_when_needs_open
        self.bench_discount_when_active_full = bench_discount_when_active_full
        self.scarcity_weight = scarcity_weight
        self.use_monte_carlo_replacement = use_monte_carlo_replacement
        self.monte_carlo_trials = max(1, int(monte_carlo_trials))
        self.monte_carlo_seed = int(monte_carlo_seed)
        self.opponent_candidate_pool = max(8, int(opponent_candidate_pool))
        self.opponent_temperature = float(opponent_temperature)
        self.opponent_need_bonus = float(opponent_need_bonus)
        self.opponent_scarcity_weight = float(opponent_scarcity_weight)
        self.opponent_bench_discount_when_needs_open = float(
            opponent_bench_discount_when_needs_open
        )
        self.opponent_bench_discount_when_active_full = float(
            opponent_bench_discount_when_active_full
        )

    def _eligible_slot_indices(self, player: Player) -> List[int]:
        indices: List[int] = []
        for idx, slot in enumerate(self.slots):
            if player.can_fill(slot):
                indices.append(idx)
        return indices

    def _max_match_for_players(self, player_ids: Sequence[str]) -> Tuple[int, Counter[str]]:
        slot_to_player = [-1] * len(self.slots)
        players = [self.state.players[player_id] for player_id in player_ids]
        edges = [self._eligible_slot_indices(player) for player in players]

        def try_match(player_idx: int, seen: List[bool]) -> bool:
            for slot_idx in edges[player_idx]:
                if seen[slot_idx]:
                    continue
                seen[slot_idx] = True
                owner = slot_to_player[slot_idx]
                if owner == -1 or try_match(owner, seen):
                    slot_to_player[slot_idx] = player_idx
                    return True
            return False

        matches = 0
        for player_idx in range(len(players)):
            seen = [False] * len(self.slots)
            if try_match(player_idx, seen):
                matches += 1

        unmet = Counter()
        for slot_idx, owner in enumerate(slot_to_player):
            if owner == -1:
                unmet[self.slots[slot_idx]] += 1
        return matches, unmet

    def active_need_summary(self, hypothetical_my_picks: Sequence[str] | None = None) -> Counter[str]:
        player_ids = list(self.state.my_picks if hypothetical_my_picks is None else hypothetical_my_picks)
        _, unmet = self._max_match_for_players(player_ids)
        return unmet

    def _sorted_available_ids(self, exclude: set[str] | None = None) -> List[str]:
        excluded = exclude or set()
        available = [player_id for player_id in self.state.available_ids if player_id not in excluded]
        if not available:
            return []

        if torch is None:
            return sorted(
                available,
                key=lambda player_id: self.state.players[player_id].projected_points,
                reverse=True,
            )

        points = torch.tensor(
            [self.state.players[player_id].projected_points for player_id in available],
            dtype=torch.float32,
        )
        order = torch.argsort(points, descending=True).tolist()
        return [available[idx] for idx in order]

    def _position_replacement(
        self,
        picks_until_next_turn: int,
        exclude: set[str] | None = None,
    ) -> Dict[str, float]:
        sorted_ids = self._sorted_available_ids(exclude=exclude)
        future_pool = sorted_ids[picks_until_next_turn:]
        replacement: Dict[str, float] = {slot: 0.0 for slot in self.unique_slots}

        for slot in self.unique_slots:
            for player_id in future_pool:
                player = self.state.players[player_id]
                if player.can_fill(slot):
                    replacement[slot] = player.projected_points
                    break
        return replacement

    def _position_best_now(self, exclude: set[str] | None = None) -> Dict[str, float]:
        sorted_ids = self._sorted_available_ids(exclude=exclude)
        best_now: Dict[str, float] = {slot: 0.0 for slot in self.unique_slots}
        for slot in self.unique_slots:
            for player_id in sorted_ids:
                player = self.state.players[player_id]
                if player.can_fill(slot):
                    best_now[slot] = player.projected_points
                    break
        return best_now

    def _build_team_pick_map(self) -> Dict[int, List[str]]:
        team_picks: Dict[int, List[str]] = {
            team: [] for team in range(1, self.state.league_size + 1)
        }
        for pick_number, event in enumerate(self.state.history, start=1):
            team = self.state.team_for_pick_number(pick_number)
            if event.from_pool and event.player_id is not None:
                team_picks[team].append(event.player_id)
        return team_picks

    def _top_available_candidates(
        self,
        available_ids: set[str],
        sorted_ids: Sequence[str],
        limit: int,
    ) -> List[str]:
        top: List[str] = []
        for player_id in sorted_ids:
            if player_id not in available_ids:
                continue
            top.append(player_id)
            if len(top) >= limit:
                break
        return top

    def _sample_index_softmax(
        self,
        scores: Sequence[float],
        temperature: float,
        rng: random.Random,
    ) -> int:
        if len(scores) == 1:
            return 0
        if temperature <= 0:
            best_score = max(scores)
            return scores.index(best_score)
        peak = max(scores)
        weights = [math.exp((score - peak) / temperature) for score in scores]
        total = sum(weights)
        if total <= 0:
            best_score = max(scores)
            return scores.index(best_score)
        threshold = rng.random() * total
        running = 0.0
        for idx, weight in enumerate(weights):
            running += weight
            if running >= threshold:
                return idx
        return len(scores) - 1

    def _simulate_single_opponent_pick(
        self,
        team_pick_ids: Sequence[str],
        available_ids: set[str],
        sorted_ids: Sequence[str],
        slot_dropoff: Dict[str, float],
        rng: random.Random,
    ) -> str | None:
        candidates = self._top_available_candidates(
            available_ids=available_ids,
            sorted_ids=sorted_ids,
            limit=self.opponent_candidate_pool,
        )
        if not candidates:
            return None

        needs = self.active_need_summary(team_pick_ids)
        has_open_active_slots = sum(needs.values()) > 0

        scores: List[float] = []
        for player_id in candidates:
            player = self.state.players[player_id]
            best_score = float("-inf")
            for slot in self.unique_slots:
                if not player.can_fill(slot):
                    continue
                if needs.get(slot, 0) > 0:
                    urgency = 1.0 + 0.2 * min(2, needs[slot])
                    score = (
                        player.projected_points
                        + self.opponent_need_bonus * urgency
                        + self.opponent_scarcity_weight * slot_dropoff[slot]
                    )
                else:
                    bench_discount = (
                        self.opponent_bench_discount_when_needs_open
                        if has_open_active_slots
                        else self.opponent_bench_discount_when_active_full
                    )
                    score = player.projected_points * bench_discount
                if score > best_score:
                    best_score = score
            scores.append(best_score)

        chosen_idx = self._sample_index_softmax(
            scores=scores,
            temperature=self.opponent_temperature,
            rng=rng,
        )
        return candidates[chosen_idx]

    def _monte_carlo_position_replacement(
        self,
        picks_until_next_turn: int,
        exclude: set[str] | None = None,
    ) -> Dict[str, float]:
        if picks_until_next_turn <= 0:
            return self._position_best_now(exclude=exclude)

        sorted_ids = self._sorted_available_ids(exclude=exclude)
        if not sorted_ids:
            return {slot: 0.0 for slot in self.unique_slots}

        best_now = self._position_best_now(exclude=exclude)
        deterministic_replacement = self._position_replacement(
            picks_until_next_turn=picks_until_next_turn,
            exclude=exclude,
        )
        slot_dropoff = {
            slot: max(0.0, best_now[slot] - deterministic_replacement[slot])
            for slot in self.unique_slots
        }

        base_team_picks = self._build_team_pick_map()
        upcoming_pick_numbers = [
            self.state.current_pick_number + offset
            for offset in range(1, picks_until_next_turn + 1)
        ]
        totals = {slot: 0.0 for slot in self.unique_slots}
        rng = random.Random(self.monte_carlo_seed + self.state.current_pick_number)

        for _ in range(self.monte_carlo_trials):
            available_ids = set(sorted_ids)
            team_picks = {team: list(player_ids) for team, player_ids in base_team_picks.items()}

            for pick_number in upcoming_pick_numbers:
                team = self.state.team_for_pick_number(pick_number)
                if team == self.state.draft_slot:
                    continue
                selected = self._simulate_single_opponent_pick(
                    team_pick_ids=team_picks[team],
                    available_ids=available_ids,
                    sorted_ids=sorted_ids,
                    slot_dropoff=slot_dropoff,
                    rng=rng,
                )
                if selected is None:
                    break
                available_ids.remove(selected)
                team_picks[team].append(selected)

            for slot in self.unique_slots:
                replacement = 0.0
                for player_id in sorted_ids:
                    if player_id not in available_ids:
                        continue
                    player = self.state.players[player_id]
                    if player.can_fill(slot):
                        replacement = player.projected_points
                        break
                totals[slot] += replacement

        return {
            slot: totals[slot] / float(self.monte_carlo_trials)
            for slot in self.unique_slots
        }

    def _feasible_after_pick(self, player_id: str) -> bool:
        hypothetical_my_picks = list(self.state.my_picks) + [player_id]
        remaining_my_picks = self.state.roster_config.total_roster_size - len(hypothetical_my_picks)
        _, unmet = self._max_match_for_players(hypothetical_my_picks)
        unfilled_active_slots = sum(unmet.values())

        if unfilled_active_slots > remaining_my_picks:
            return False

        available_after_pick = self.state.available_ids - {player_id}
        for slot, missing in unmet.items():
            if missing == 0:
                continue
            eligible_available = 0
            for available_id in available_after_pick:
                if self.state.players[available_id].can_fill(slot):
                    eligible_available += 1
            if eligible_available < missing:
                return False
        return True

    def recommend(self, top_n: int = 12) -> List[Recommendation]:
        if top_n <= 0:
            return []

        picks_until_next_turn = self.state.picks_until_my_pick_after_current()
        current_needs = self.active_need_summary()
        has_open_active_slots = sum(current_needs.values()) > 0

        if self.use_monte_carlo_replacement and picks_until_next_turn > 0:
            replacement_next = self._monte_carlo_position_replacement(
                picks_until_next_turn=picks_until_next_turn,
            )
        else:
            replacement_next = self._position_replacement(
                picks_until_next_turn=picks_until_next_turn
            )
        best_now = self._position_best_now()
        dropoff = {
            slot: max(0.0, best_now[slot] - replacement_next[slot]) for slot in self.unique_slots
        }

        recommendations: List[Recommendation] = []
        for player_id in self.state.available_ids:
            player = self.state.players[player_id]
            feasible = self._feasible_after_pick(player_id)
            if not feasible:
                continue

            best_slot = None
            best_score = float("-inf")
            best_replacement = 0.0
            best_dropoff = 0.0

            for slot in self.unique_slots:
                if not player.can_fill(slot):
                    continue
                if current_needs.get(slot, 0) > 0:
                    base = player.projected_points - replacement_next[slot]
                    score = base + self.scarcity_weight * dropoff[slot]
                else:
                    discount = (
                        self.bench_discount_when_needs_open
                        if has_open_active_slots
                        else self.bench_discount_when_active_full
                    )
                    score = player.projected_points * discount

                if score > best_score:
                    best_score = score
                    best_slot = slot
                    best_replacement = replacement_next[slot]
                    best_dropoff = dropoff[slot]

            if best_slot is None:
                continue

            rationale = (
                f"slot={best_slot} need={current_needs.get(best_slot, 0)} "
                f"replacement_next={best_replacement:.1f} dropoff={best_dropoff:.1f}"
            )
            recommendations.append(
                Recommendation(
                    player_id=player.player_id,
                    name=player.name,
                    positions=player.positions,
                    projected_points=player.projected_points,
                    score=best_score,
                    suggested_slot=best_slot,
                    replacement_at_next_pick=best_replacement,
                    scarcity_dropoff=best_dropoff,
                    feasible=True,
                    rationale=rationale,
                )
            )

        recommendations.sort(
            key=lambda rec: (rec.score, rec.projected_points),
            reverse=True,
        )
        return recommendations[:top_n]
