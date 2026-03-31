from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


Vector = Tuple[int, ...]
Weighing = Tuple[Tuple[int, ...], Tuple[int, ...]]


@dataclass(frozen=True)
class Strategy:
    n: int
    round_count: int
    resolve_weight: bool = False
    weighings: Tuple[Weighing, ...] = ()
    codebook: Tuple[Vector, ...] = ()

    @property
    def rounds(self) -> int:
        return self.round_count


@dataclass(frozen=True)
class TraceStep:
    round_number: int
    left: Tuple[int, ...]
    right: Tuple[int, ...]
    result: int
    note: str = ""


def minimum_weighings(n: int, resolve_weight: bool = False) -> int:
    if n <= 0:
        raise ValueError("n must be positive")

    rounds = 1
    while max_supported_balls(rounds, resolve_weight=resolve_weight) < n:
        rounds += 1
    return rounds


def max_supported_balls(rounds: int, resolve_weight: bool = False) -> int:
    if rounds <= 0:
        return 0
    # 两种目标对应两种理论上界：
    # - 默认模式：优先找出异常球，轻重能判就判，不能判就返回 unknown
    # - 强模式：必须同时判断 heavy / light
    if resolve_weight:
        return (3**rounds - 3) // 2
    return (3**rounds - 1) // 2


def find_special_ball(
    balls: Sequence[int], strategy: Optional[Strategy] = None
) -> Tuple[int, int, int]:
    count, idx, weight, _ = trace_special_ball(balls, strategy)
    return count, idx, weight


def trace_special_ball(
    balls: Sequence[int], strategy: Optional[Strategy] = None
) -> Tuple[int, int, int, Tuple[TraceStep, ...]]:
    index, weight = _validate_balls(balls)
    strategy = strategy or build_strategy(len(balls))
    if strategy.n != len(balls):
        raise ValueError("strategy size does not match balls length")

    if strategy.resolve_weight:
        count, resolved_idx, resolved_weight, steps = _trace_fixed_strategy(balls, strategy)
    else:
        solver = _AdaptiveSolver(balls)
        resolved_idx, resolved_weight = solver.solve_unknown(tuple(range(len(balls))), strategy.rounds)
        count = len(solver.steps)
        steps = tuple(solver.steps)

    if resolved_idx != index:
        raise RuntimeError(f"strategy mismatch: expected ball {index}, got ball {resolved_idx}")
    if strategy.resolve_weight and resolved_weight != weight:
        raise RuntimeError(f"strategy mismatch: expected weight {weight}, got {resolved_weight}")
    if not strategy.resolve_weight and resolved_weight not in (0, weight):
        raise RuntimeError(
            f"strategy mismatch: expected weight {weight} or unknown, got {resolved_weight}"
        )

    return count, resolved_idx, resolved_weight, steps


def build_strategy(n: int, resolve_weight: bool = False) -> Strategy:
    rounds = minimum_weighings(n, resolve_weight=resolve_weight)
    if not resolve_weight:
        return Strategy(n=n, round_count=rounds, resolve_weight=False)

    codebook = _build_codebook(n, rounds)
    weighings = tuple(_build_weighing(codebook, column) for column in range(rounds))
    return Strategy(
        n=n,
        round_count=rounds,
        resolve_weight=True,
        weighings=weighings,
        codebook=codebook,
    )


def verify_strategy(n: int, strategy: Optional[Strategy] = None) -> bool:
    strategy = strategy or build_strategy(n)
    for idx in range(n):
        for weight in (-1, 1):
            balls = [0] * n
            balls[idx] = weight
            count, resolved_idx, resolved_weight = find_special_ball(balls, strategy)
            if count > strategy.rounds or resolved_idx != idx:
                return False
            if strategy.resolve_weight and resolved_weight != weight:
                return False
            if not strategy.resolve_weight and resolved_weight not in (0, weight):
                return False
    return True


def describe_strategy(strategy: Strategy) -> str:
    mode = "ball+weight" if strategy.resolve_weight else "ball-first adaptive"
    lines = [f"n={strategy.n}, rounds={strategy.rounds}, mode={mode}"]
    if strategy.weighings:
        for step, (left, right) in enumerate(strategy.weighings, start=1):
            lines.append(f"round {step}: left={list(left)} right={list(right)}")
    else:
        lines.append("weighings are generated adaptively from the current result path")
    return "\n".join(lines)


class _AdaptiveSolver:
    # 默认模式下不预先生成整棵固定策略树，而是沿着“当前称重结果”递归构造。
    #
    # 这里有 3 种核心状态：
    # 1. solve_unknown:
    #    没有标准球，异常球的轻重也未知。
    # 2. solve_with_good:
    #    已经拿到一批标准球，但异常球的轻重还未知。
    # 3. solve_signed:
    #    每个候选球一旦异常时应当是偏重还是偏轻，已经固定。
    def __init__(self, balls: Sequence[int]) -> None:
        self.balls = balls
        self.steps: List[TraceStep] = []

    def solve_unknown(self, candidates: Tuple[int, ...], rounds: int) -> Tuple[int, int]:
        if len(candidates) == 1:
            return candidates[0], 0
        if rounds <= 0:
            raise RuntimeError("ran out of weighings in unknown state")
        if len(candidates) > max_supported_balls(rounds):
            raise RuntimeError("too many unknown candidates for the remaining rounds")

        # 把 candidates 拆成 left / right / rest：
        # - left 和 right 先互称
        # - 若平衡，则异常球在 rest，且 left+right 都成为标准球
        # - 若不平衡，则异常球在 left 或 right 中，并且轻重方向被这次结果固定
        balance_capacity = _max_with_good(rounds - 1)
        max_signed_pairs = _max_signed(rounds - 1) // 2
        chosen_rest = None
        upper = min(balance_capacity, len(candidates) - 2)
        for rest_size in range(upper, 0, -1):
            if (len(candidates) - rest_size) % 2 != 0:
                continue
            side_size = (len(candidates) - rest_size) // 2
            future_side = _with_good_side_size(rest_size, rounds - 1)
            if side_size <= max_signed_pairs and 2 * side_size >= future_side:
                chosen_rest = rest_size
                break
        if chosen_rest is None:
            raise RuntimeError("could not split the unknown state")

        side_size = (len(candidates) - chosen_rest) // 2
        left = candidates[:side_size]
        right = candidates[side_size : 2 * side_size]
        rest = candidates[2 * side_size :]

        result = self._weigh(left, right, "unknown vs unknown")
        if result == 0:
            return self.solve_with_good(rest, left + right, rounds - 1)

        # 不平衡后，候选会变成“带符号候选”：
        # 例如左重时，left 里的球只能偏重，right 里的球只能偏轻。
        signed: List[Tuple[int, int]] = []
        for idx in left:
            signed.append((idx, 1 if result == -1 else -1))
        for idx in right:
            signed.append((idx, -1 if result == -1 else 1))
        return self.solve_signed(tuple(signed), rest, rounds - 1)

    def solve_with_good(
        self, candidates: Tuple[int, ...], good: Tuple[int, ...], rounds: int
    ) -> Tuple[int, int]:
        if len(candidates) == 1:
            return candidates[0], 0
        if rounds <= 0:
            raise RuntimeError("ran out of weighings with known good balls")
        if len(candidates) > _max_with_good(rounds):
            raise RuntimeError("too many candidates for the remaining with-good rounds")

        # 这里最像“正常人会想出来的称法”：
        # 把一批 suspects 放左盘，用同样数量的 known-good 放右盘。
        # - 平衡：这批 suspects 全正常，异常球在 rest
        # - 不平衡：异常球就在这批 suspects 中，轻重方向随结果确定
        rest_size = max(0, len(candidates) - _max_signed(rounds - 1))
        side_size = len(candidates) - rest_size
        if side_size > len(good):
            raise RuntimeError("not enough good balls available to support the weighing")

        weighed = candidates[:side_size]
        rest = candidates[side_size:]
        fillers = good[:side_size]

        result = self._weigh(weighed, fillers, "suspects vs known-good")
        if result == 0:
            return self.solve_with_good(rest, good + weighed, rounds - 1)

        sign = 1 if result == -1 else -1
        signed = tuple((idx, sign) for idx in weighed)
        return self.solve_signed(signed, good + rest, rounds - 1)

    def solve_signed(
        self, candidates: Tuple[Tuple[int, int], ...], good: Tuple[int, ...], rounds: int
    ) -> Tuple[int, int]:
        if len(candidates) == 1:
            return candidates[0]
        if rounds <= 0:
            raise RuntimeError("ran out of weighings in signed state")
        if len(candidates) > _max_signed(rounds):
            raise RuntimeError("too many signed candidates for the remaining rounds")

        # signed 状态里的每个元素都是 (球号, sign)：
        # - sign = +1: 如果它异常，它应当是偏重
        # - sign = -1: 如果它异常，它应当是偏轻
        #
        # 目标是把候选拆成三支，分别对应：
        # - 左重时保留
        # - 右重时保留
        # - 平衡时保留
        capacity = _max_signed(rounds - 1)
        split = _plan_signed_split(candidates, capacity, good)
        left_actual = split["left_pan"]
        right_actual = split["right_pan"]
        branch_left = split["branch_left"]
        branch_right = split["branch_right"]
        branch_balance = split["branch_balance"]
        carried_good = split["carried_good"]

        result = self._weigh(
            left_actual,
            right_actual,
            "known-sign candidates",
        )
        if result == 0:
            return self.solve_signed(branch_balance, carried_good + tuple(idx for idx, _ in branch_left + branch_right), rounds - 1)
        if result == -1:
            next_candidates = branch_left
            eliminated = branch_right + branch_balance
        else:
            next_candidates = branch_right
            eliminated = branch_left + branch_balance
        return self.solve_signed(next_candidates, carried_good + tuple(idx for idx, _ in eliminated), rounds - 1)

    def _weigh(self, left: Iterable[int], right: Iterable[int], note: str) -> int:
        left_tuple = tuple(left)
        right_tuple = tuple(right)
        result = _simulate_weighing(self.balls, left_tuple, right_tuple)
        self.steps.append(
            TraceStep(
                round_number=len(self.steps) + 1,
                left=left_tuple,
                right=right_tuple,
                result=result,
                note=note,
            )
        )
        return result


def _plan_signed_split(
    candidates: Tuple[Tuple[int, int], ...], capacity: int, good: Tuple[int, ...]
) -> Dict[str, object]:
    # signed 状态的分组构造器。
    #
    # branch_left / branch_right / branch_balance
    # 表示称重结果为左重 / 右重 / 平衡时，各自应保留的候选集。
    #
    # 真正上秤时：
    # - branch_left 中 sign=+1 的球放左盘
    # - branch_left 中 sign=-1 的球放右盘
    #   这样“左重”时它们仍然成立
    # - branch_right 反过来摆
    #
    # 左右盘数量不够对齐时，允许用标准球补齐。
    positives = [item for item in candidates if item[1] == 1]
    negatives = [item for item in candidates if item[1] == -1]
    total = len(candidates)
    good_count = len(good)
    best: Optional[Tuple[int, int, int, int, int]] = None

    min_balance = max(0, total - 2 * capacity)
    max_balance = min(capacity, total)
    for balance_size in range(min_balance, max_balance + 1):
        remaining = total - balance_size
        min_left = max(0, remaining - capacity)
        max_left = min(capacity, remaining)
        target_left = remaining // 2
        for delta in range(0, capacity + 1):
            for left_size in (target_left - delta, target_left + delta):
                if left_size < min_left or left_size > max_left:
                    continue
                right_size = remaining - left_size
                if right_size < 0 or right_size > capacity:
                    continue

                min_left_pos = max(0, left_size - len(negatives))
                max_left_pos = min(len(positives), left_size)
                for left_pos in range(min_left_pos, max_left_pos + 1):
                    left_neg = left_size - left_pos
                    remaining_pos = len(positives) - left_pos
                    remaining_neg = len(negatives) - left_neg

                    min_right_pos = max(0, right_size - remaining_neg)
                    max_right_pos = min(remaining_pos, right_size)
                    for right_pos in range(min_right_pos, max_right_pos + 1):
                        right_neg = right_size - right_pos
                        balance_pos = remaining_pos - right_pos
                        balance_neg = remaining_neg - right_neg
                        if balance_pos < 0 or balance_neg < 0:
                            continue

                        left_pan_size = left_pos + right_neg
                        right_pan_size = left_neg + right_pos
                        fillers_needed = abs(left_pan_size - right_pan_size)
                        if fillers_needed > good_count:
                            continue

                        score = (
                            max(left_size, right_size, balance_size),
                            fillers_needed,
                            balance_size,
                            left_size,
                            left_pos,
                        )
                        if best is None or score < best:
                            best = (balance_size, left_size, left_pos, right_pos, fillers_needed)
            if best is not None:
                break
        if best is not None:
            break

    if best is None:
        raise RuntimeError("could not split the signed state")

    balance_size, left_size, left_pos, right_pos, fillers_needed = best
    right_size = total - balance_size - left_size
    left_neg = left_size - left_pos
    right_neg = right_size - right_pos

    branch_left = tuple(positives[:left_pos] + negatives[:left_neg])
    remaining_pos = positives[left_pos:]
    remaining_neg = negatives[left_neg:]
    branch_right = tuple(remaining_pos[:right_pos] + remaining_neg[:right_neg])
    branch_balance = tuple(remaining_pos[right_pos:] + remaining_neg[right_neg:])

    left_pan = [idx for idx, sign in branch_left if sign == 1]
    left_pan.extend(idx for idx, sign in branch_right if sign == -1)
    right_pan = [idx for idx, sign in branch_left if sign == -1]
    right_pan.extend(idx for idx, sign in branch_right if sign == 1)

    if len(left_pan) < len(right_pan):
        left_pan.extend(good[: len(right_pan) - len(left_pan)])
    elif len(right_pan) < len(left_pan):
        right_pan.extend(good[: len(left_pan) - len(right_pan)])

    return {
        "left_pan": tuple(left_pan),
        "right_pan": tuple(right_pan),
        "branch_left": branch_left,
        "branch_right": branch_right,
        "branch_balance": branch_balance,
        "carried_good": good,
    }


def _max_with_good(rounds: int) -> int:
    if rounds < 0:
        return 0
    # 已有标准球时的容量：
    # f(k) = (3^k + 1) / 2
    return (3**rounds + 1) // 2


def _max_signed(rounds: int) -> int:
    if rounds < 0:
        return 0
    # signed 状态容量最干净：每一轮把候选切成 3 支，所以就是 3^k。
    return 3**rounds


def _with_good_side_size(candidates: int, rounds: int) -> int:
    if candidates <= 1 or rounds <= 0:
        return 0
    # solve_with_good 下一轮真正上秤的 suspects 数量。
    return candidates - max(0, candidates - _max_signed(rounds - 1))


def _trace_fixed_strategy(
    balls: Sequence[int], strategy: Strategy
) -> Tuple[int, int, int, Tuple[TraceStep, ...]]:
    if not strategy.weighings or not strategy.codebook:
        raise RuntimeError("missing fixed strategy data")

    steps: List[TraceStep] = []
    outcome = []
    for round_number, (left, right) in enumerate(strategy.weighings, start=1):
        result = _simulate_weighing(balls, left, right)
        steps.append(TraceStep(round_number=round_number, left=left, right=right, result=result))
        outcome.append(result)

    lookup = _outcome_lookup(strategy.codebook)
    try:
        resolved_idx, resolved_weight = lookup[tuple(outcome)]
    except KeyError as exc:
        raise RuntimeError(f"strategy could not resolve outcome {tuple(outcome)}") from exc

    return len(steps), resolved_idx, resolved_weight, tuple(steps)


def _validate_balls(balls: Sequence[int]) -> Tuple[int, int]:
    if not balls:
        raise ValueError("balls must not be empty")

    anomaly_indexes = [idx for idx, value in enumerate(balls) if value != 0]
    if len(anomaly_indexes) != 1:
        raise ValueError("balls must contain exactly one non-zero entry")

    index = anomaly_indexes[0]
    weight = balls[index]
    if weight not in (-1, 1):
        raise ValueError("the abnormal ball must be encoded as -1 or 1")
    return index, weight


def _simulate_weighing(balls: Sequence[int], left: Iterable[int], right: Iterable[int]) -> int:
    left_weight = sum(balls[idx] for idx in left)
    right_weight = sum(balls[idx] for idx in right)
    if left_weight > right_weight:
        return -1
    if left_weight < right_weight:
        return 1
    return 0


def _build_weighing(codebook: Sequence[Vector], column: int) -> Weighing:
    left = tuple(idx for idx, vector in enumerate(codebook) if vector[column] == -1)
    right = tuple(idx for idx, vector in enumerate(codebook) if vector[column] == 1)
    return left, right


def _outcome_lookup(codebook: Sequence[Vector]) -> Dict[Vector, Tuple[int, int]]:
    lookup: Dict[Vector, Tuple[int, int]] = {}
    for idx, vector in enumerate(codebook):
        lookup[vector] = (idx, 1)
        lookup[_negate(vector)] = (idx, -1)
    return lookup


def _build_codebook(n: int, rounds: int) -> Tuple[Vector, ...]:
    vectors = _canonical_vectors(rounds)
    selected = _select_vectors(vectors, n)
    return tuple(selected)


def _canonical_vectors(rounds: int) -> List[Vector]:
    # 强模式仍然使用固定三进制编码。
    # 一个球在每轮只有 3 种位置：
    # -1: 左盘, 0: 不上秤, +1: 右盘
    #
    # 如果球偏重，结果串对应 v；
    # 如果球偏轻，结果串对应 -v。
    # 所以不能同时使用 v 和 -v 代表两个不同球。
    vectors: List[Vector] = []

    def walk(position: int, prefix: List[int]) -> None:
        if position == rounds:
            if any(prefix):
                vectors.append(tuple(prefix))
            return

        for value in (-1, 0, 1):
            prefix.append(value)
            walk(position + 1, prefix)
            prefix.pop()

    walk(0, [])

    canonical: List[Vector] = []
    for vector in vectors:
        if vector < _negate(vector):
            canonical.append(vector)
    canonical.sort(key=lambda item: (-sum(1 for value in item if value != 0), item))
    return canonical


def _select_vectors(vectors: Sequence[Vector], target_count: int) -> List[Vector]:
    # 强模式旧解法：
    # 从候选三进制向量里挑出 target_count 个，
    # 要求每一列的和都为 0，这样每轮左右盘球数才相等。
    @lru_cache(maxsize=None)
    def search(
        index: int, chosen: int, sums: Tuple[int, ...]
    ) -> Optional[Tuple[Tuple[int, Vector], ...]]:
        if chosen == target_count:
            return tuple() if all(value == 0 for value in sums) else None

        remaining_slots = target_count - chosen
        remaining_vectors = len(vectors) - index
        if remaining_vectors < remaining_slots:
            return None

        for axis_sum in sums:
            if abs(axis_sum) > remaining_slots:
                return None

        if index == len(vectors):
            return None

        vector = vectors[index]

        skip = search(index + 1, chosen, sums)
        if skip is not None:
            return skip

        positive_sums = tuple(current + delta for current, delta in zip(sums, vector))
        positive = search(index + 1, chosen + 1, positive_sums)
        if positive is not None:
            return ((1, vector),) + positive

        negative_vector = _negate(vector)
        negative_sums = tuple(current + delta for current, delta in zip(sums, negative_vector))
        negative = search(index + 1, chosen + 1, negative_sums)
        if negative is not None:
            return ((-1, vector),) + negative

        return None

    zero = tuple(0 for _ in vectors[0])
    solution = search(0, 0, zero)
    if solution is None:
        raise RuntimeError(f"could not build a balanced codebook for n={target_count}")

    selected: List[Vector] = []
    for sign, vector in solution:
        selected.append(vector if sign == 1 else _negate(vector))
    return selected


def _negate(vector: Vector) -> Vector:
    return tuple(-value for value in vector)
