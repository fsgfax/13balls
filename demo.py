from __future__ import annotations

import argparse
from typing import Sequence

from odd_ball import build_strategy, trace_special_ball


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Show the fixed weighing strategy and a full simulation trace."
    )
    parser.add_argument("n", type=int, help="number of balls")
    parser.add_argument("index", type=int, help="abnormal ball number, starting from 1")
    parser.add_argument("weight", type=int, choices=(-1, 1), help="-1 for lighter, 1 for heavier")
    parser.add_argument(
        "--resolve-weight",
        action="store_true",
        help="require the strategy to always distinguish heavier vs lighter",
    )
    args = parser.parse_args()

    if args.index < 1 or args.index > args.n:
        raise SystemExit("index must be between 1 and n")

    balls = [0] * args.n
    balls[args.index - 1] = args.weight

    strategy = build_strategy(args.n, resolve_weight=args.resolve_weight)
    count, found_index, found_weight, steps = trace_special_ball(balls, strategy)

    print("13balls")
    print("=" * 8)
    print(f"Mode              : {'ball + weight' if strategy.resolve_weight else 'ball first, weight if possible'}")
    print(f"Total balls       : {args.n}")
    print(f"Hidden odd ball   : #{args.index}")
    print(f"Hidden weight     : {format_weight(args.weight)}")
    print(f"Minimum weighings : {strategy.rounds}")
    print()

    print("Weighing Trace")
    print("-" * 13)
    for step in steps:
        print(f"Round {step.round_number:<2} {format_ball_group(step.left)}  vs  {format_ball_group(step.right)}")
        print(f"         Result : {format_result(step.result)}")
        print(f"         State  : {step.note}")
        print()

    print("Verdict")
    print("-" * 7)
    print(f"Used weighings : {count}")
    print(f"Odd ball       : #{found_index + 1}")
    print(f"Weight         : {format_weight(found_weight)}")
    print(f"Path           : {' '.join(format_result_code(step.result) for step in steps)}")
    print()


def format_ball_group(group: Sequence[int]) -> str:
    labels = [str(idx + 1) for idx in group]
    return "[" + ", ".join(labels) + "]"


def format_result(result: int) -> str:
    if result == -1:
        return "left heavier"
    if result == 1:
        return "right heavier"
    return "balanced"


def format_result_code(result: int) -> str:
    if result == -1:
        return "L"
    if result == 1:
        return "R"
    return "="


def format_weight(weight: int) -> str:
    if weight == 1:
        return "heavier (+1)"
    if weight == -1:
        return "lighter (-1)"
    return "unknown (0)"


if __name__ == "__main__":
    main()
