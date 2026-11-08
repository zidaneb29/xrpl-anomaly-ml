"""Single-threaded isolation trees with seeded subsampling and exact leaf correction."""
from dataclasses import dataclass
from math import isfinite
from random import Random


@dataclass(frozen=True)
class Split:
    column: int
    cut: float
    left: object
    right: object


def tree(rows, columns, depth, rng, correction):
    if len(rows) > 1 and depth:
        # A random ordering makes the first usable column uniform among varying columns.
        for column in rng.sample(columns, len(columns)):
            values = [row[column] for row in rows]
            low, high = min(values), max(values)
            if low < high:
                cut = rng.uniform(low, high)
                if cut <= low:
                    cut = high
                left, right = [], []
                for row in rows:
                    (left if row[column] < cut else right).append(row)
                return Split(column, cut, tree(left, columns, depth - 1, rng, correction),
                             tree(right, columns, depth - 1, rng, correction))
    return correction[len(rows)]


@dataclass(frozen=True)
class IsolationForest:
    columns: tuple
    trees: tuple
    normalizer: float

    @classmethod
    def fit(cls, rows, *, size, seed, trees=64):
        if len(rows) < 2 or size < 2 or trees < 1:
            raise ValueError("expected at least two training rows and one tree")
        columns = tuple(i for i, values in enumerate(zip(*rows, strict=True))
                        if min(values) < max(values))
        if not rows[0] or any(not isfinite(value) for row in rows for value in row):
            raise ValueError("expected finite nonempty features")
        size = min(size, len(rows))
        # c(n) = 2 H(n) - 2 for n >= 1.
        correction = [0.0, 0.0]
        for n in range(2, size + 1):
            correction.append(correction[-1] + 2 / n)
        rng = Random(seed)
        depth = (size - 1).bit_length()
        forest = tuple(tree(rng.sample(rows, size), columns, depth, rng, correction)
                       for _ in range(trees))
        return cls(columns, forest, correction[size] * trees)

    def score(self, row):
        total = 0.0
        for node in self.trees:
            depth = 0
            while isinstance(node, Split):
                node = node.left if row[node.column] < node.cut else node.right
                depth += 1
            total += depth + node
        return 2 ** (-total / self.normalizer)
