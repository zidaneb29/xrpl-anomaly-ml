"""Controlled interventions on copies of block-local eligible payment streams."""
from bisect import bisect_left
from collections import Counter, defaultdict, deque
from random import Random

from .expansion_report import scored_features
from .features import WINDOW

FAMILIES = {"amount": (2, 4), "burst": (2, 4), "concentration": (1, 3)}
SEEDS = (17, 43)


def candidates(ledgers, start, amount_limits):
    """Use original prior-ledger context to construct common eligibility across levels."""
    low, high = amount_limits
    closes = [close for _, close, _ in ledgers]
    history = defaultdict(deque)
    by_family = {family: defaultdict(list) for family in FAMILIES}
    for offset, (_, close, payments) in enumerate(ledgers):
        for payment in payments:
            _, _, sender, receiver, amount, _ = payment
            prior = history[sender]
            while prior and prior[0][0] < close - WINDOW:
                prior.popleft()
            if not start <= close < start + 1800:
                continue
            direction = 1 if low <= amount and 4 * amount <= high else -1
            if direction == 1 or (low <= amount // 4 < amount <= high):
                by_family["amount"][sender].append((offset, payment, direction))
            counts = Counter(other for _, other in prior)
            alternatives = sorted(other for other, count in counts.items()
                                  if other != receiver and count >= 2 and count > counts[receiver])
            if counts[receiver] and alternatives:
                target = max(alternatives, key=counts.get)
                by_family["concentration"][sender].append((offset, payment, target))
            if prior:
                anchor = prior[-1][0]
                gap = close - anchor
                targets = tuple(bisect_left(closes, anchor + max(1, gap // level))
                                for level in FAMILIES["burst"])
                if (15 <= gap <= 120 and targets[1] < targets[0] < offset
                        and closes[targets[1]] >= start):
                    by_family["burst"][sender].append((offset, payment, targets))
        for _, _, sender, receiver, _, _ in payments:
            history[sender].append((close, receiver))
    for sender, events in by_family["concentration"].items():
        targets = Counter(event[2] for event in events)
        target = max(sorted(targets), key=targets.get)
        by_family["concentration"][sender] = [event for event in events if event[2] == target]
    return by_family


def intervene(ledgers, family, level, eligible, seed, size):
    """Apply at most one sender intervention, with original identities preserved."""
    rng = Random(seed)
    units = sorted(eligible)
    rng.shuffle(units)
    changes = {}
    accepted = 0
    for sender in units:
        events = eligible[sender]
        if family == "concentration" and len(events) < max(FAMILIES[family]):
            continue
        count = level if family == "concentration" else 1
        # Sample the same ordered candidate set at each severity.
        chosen = rng.sample(events, max(FAMILIES[family]) if family == "concentration" else 1)
        for offset, payment, target in chosen[:count]:
            position, identity, source, receiver, amount, fee = payment
            if family == "amount":
                amount = amount * level if target == 1 else amount // level
            elif family == "burst":
                offset = target[FAMILIES[family].index(level)]
                position = -1
            else:
                receiver = target
            changes[identity] = offset, (position, identity, source, receiver, amount, fee)
        accepted += 1
        if accepted >= size:
            break

    rows = [[payment for payment in payments if payment[1] not in changes]
            for _, _, payments in ledgers]
    for offset, payment in changes.values():
        if payment[0] == -1:
            position = 1 + max((row[0] for row in rows[offset]), default=-1)
            payment = (position, *payment[1:])
        rows[offset].append(payment)
    modified = [(index, close, tuple(sorted(payments)))
                for (index, close, _), payments in zip(ledgers, rows, strict=True)]
    return modified, set(changes)


def scenario(ledgers, start, original, family, level, eligible, seed):
    modified, labels = intervene(ledgers, family, level, eligible, seed,
                                 max(1, len(original) // 100))
    replayed = {row[2]: row for row in scored_features(modified, start)}
    if replayed.keys() != original.keys() or not labels <= replayed.keys():
        raise ValueError("intervention changed scoring eligibility")
    affected = {key for key in replayed.keys() - labels if replayed[key][-1] != original[key][-1]}
    return replayed, labels, affected
