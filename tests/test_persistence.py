"""Exact binary64 snapshots must fail closed on changed or corrupt scene data."""

import base64
import hashlib
import json
import math
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PictologicsSlicer"))
from PictologicsLib.persistence import decode_values, encode_values, table_identity  # noqa: E402


class PersistenceTest(unittest.TestCase):
    def setUp(self):
        self.identity = table_identity(["run", "key"], [["a", "mean"], ["a", "volume"]])

    def test_round_trip_exact_and_rounded_binary64_values(self):
        values = [206.64972537299272, -math.pi, 1.2345678901234567e-200, 1e200, -0.0, float("nan")]
        snapshot = encode_values(values, self.identity)
        for stored in (values, [float(format(value, ".6g")) for value in values]):
            recovered = decode_values(snapshot, self.identity, stored)
            self.assertEqual(struct.pack(">6d", *values), struct.pack(">6d", *recovered))
        self.assertEqual(decode_values(encode_values([], self.identity), self.identity, []), ())

    def test_identity_binds_columns_row_order_and_all_text_cells(self):
        for columns, rows in ((["key", "run"], [["a", "mean"], ["a", "volume"]]),
                              (["run", "key"], [["a", "volume"], ["a", "mean"]]),
                              (["run", "key"], [["b", "mean"], ["a", "volume"]])):
            self.assertNotEqual(table_identity(columns, rows), self.identity)

    def test_rejects_changed_data_instead_of_overwriting_edits(self):
        snapshot = encode_values([math.pi, 42.0], self.identity)
        for identity, values in (("wrong", [3.14159, 42.0]), (self.identity, [3.14159]),
                                 (self.identity, [99.0, 42.0]), (self.identity, [math.pi, float("nan")])):
            with self.subTest(identity=identity, values=values), self.assertRaises(ValueError):
                decode_values(snapshot, identity, values)

    def test_rejects_malformed_and_oversized_snapshots(self):
        valid = json.loads(encode_values([math.pi], self.identity))
        invalid = ["bad json", "[]", "{}", " " * 1040]
        for key, value in (("version", 2), ("version", True), ("count", True),
                           ("sha256", "bad"), ("float64_be", "bad!"),
                           ("float64_be", ""), ("float64_be", []), ("float64_be", "é")):
            invalid.append(json.dumps({**valid, key: value}))
        invalid.append(json.dumps({**valid, "extra": "field"}))
        for snapshot in invalid:
            with self.subTest(snapshot=snapshot[:60]), self.assertRaises(ValueError):
                decode_values(snapshot, self.identity, [3.14159])

    def test_infinity_is_never_accepted_even_with_a_matching_checksum(self):
        with self.assertRaises(ValueError):
            encode_values([float("inf")], self.identity)
        valid = json.loads(encode_values([1.0], self.identity))
        raw = struct.pack(">d", float("inf"))
        valid.update(float64_be=base64.b64encode(raw).decode("ascii"), sha256=hashlib.sha256(raw).hexdigest())
        with self.assertRaises(ValueError):
            decode_values(json.dumps(valid), self.identity, [float("inf")])


if __name__ == "__main__":
    unittest.main()
