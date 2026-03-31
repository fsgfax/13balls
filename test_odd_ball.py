import unittest

from odd_ball import (
    build_strategy,
    find_special_ball,
    minimum_weighings,
    verify_strategy,
)


class OddBallTests(unittest.TestCase):
    def test_find_special_ball_heavy(self) -> None:
        count, idx, weight = find_special_ball([0, 0, 0, 1, 0, 0])
        self.assertEqual((count, idx, weight), (3, 3, 1))

    def test_find_special_ball_light(self) -> None:
        count, idx, weight = find_special_ball([0, -1, 0])
        self.assertEqual((count, idx, weight), (2, 1, -1))

    def test_single_ball_can_be_found_with_unknown_weight(self) -> None:
        count, idx, weight = find_special_ball([1])
        self.assertEqual((count, idx, weight), (0, 0, 0))

    def test_minimum_weighings(self) -> None:
        self.assertEqual(minimum_weighings(1), 1)
        self.assertEqual(minimum_weighings(3), 2)
        self.assertEqual(minimum_weighings(12), 3)
        self.assertEqual(minimum_weighings(13), 3)
        self.assertEqual(minimum_weighings(21), 4)

    def test_minimum_weighings_when_weight_must_be_known(self) -> None:
        self.assertEqual(minimum_weighings(1, resolve_weight=True), 2)
        self.assertEqual(minimum_weighings(12, resolve_weight=True), 3)
        self.assertEqual(minimum_weighings(13, resolve_weight=True), 4)

    def test_verify_13_balls(self) -> None:
        strategy = build_strategy(13)
        self.assertEqual(strategy.rounds, 3)
        self.assertTrue(verify_strategy(13, strategy))

    def test_verify_21_balls(self) -> None:
        strategy = build_strategy(21)
        self.assertEqual(strategy.rounds, 4)
        self.assertTrue(verify_strategy(21, strategy))

    def test_verify_13_balls_with_weight_resolution(self) -> None:
        strategy = build_strategy(13, resolve_weight=True)
        self.assertEqual(strategy.rounds, 4)
        self.assertTrue(verify_strategy(13, strategy))


if __name__ == "__main__":
    unittest.main()
