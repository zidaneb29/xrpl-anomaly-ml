"""Earlier-ledger feature replay with explicit warm-up and gap boundaries."""
from collections import Counter, defaultdict, deque
from math import log1p

WINDOW = 600
SCHEMA_VERSION = 1
STATIC = ("log_amount_drops", "log_fee_drops")
FEATURES = STATIC + tuple(
    f"{side}_{key}"
    for side in ("sender", "receiver")
    for key in ("log_in_count", "log_out_count", "log_in_drops", "log_out_drops",
                "recency_seconds", "unseen", "log_in_counterparties", "log_out_counterparties")
) + ("log_prior_edge_count", "sender_out_concentration", "sender_no_outgoing")


class History:
    def __init__(self):
        self.incoming = defaultdict(Counter)
        self.outgoing = defaultdict(Counter)
        self.in_volume = Counter()
        self.out_volume = Counter()
        self.activity = defaultdict(deque)

    def update(self, close, payment, direction):
        _, _, sender, receiver, amount, _ = payment
        for edges, volume, account, other in (
            (self.outgoing, self.out_volume, sender, receiver),
            (self.incoming, self.in_volume, receiver, sender),
        ):
            edges[account][other] += direction
            volume[account] += direction * amount
            if not edges[account][other]:
                del edges[account][other]
            if not edges[account]:
                del edges[account]
                del volume[account]
        for account in (sender, receiver):
            if direction > 0:
                self.activity[account].append(close)
            else:
                self.activity[account].popleft()
                if not self.activity[account]:
                    del self.activity[account]

    def endpoint(self, account, close):
        incoming = self.incoming.get(account, {})
        outgoing = self.outgoing.get(account, {})
        activity = self.activity.get(account)
        return (log1p(sum(incoming.values())), log1p(sum(outgoing.values())),
                log1p(self.in_volume[account]), log1p(self.out_volume[account]),
                close - activity[-1] if activity else WINDOW, int(not activity),
                log1p(len(incoming)), log1p(len(outgoing)))

    def context(self, sender, receiver, close):
        edges = self.outgoing.get(sender, {})
        count = sum(edges.values())
        concentration = sum(n * n for n in edges.values()) / (count * count) if count else 0
        return (*self.endpoint(sender, close), *self.endpoint(receiver, close),
                log1p(edges.get(receiver, 0)), concentration, int(not count))


def features(ledgers):
    pending = deque()
    history = History()
    first_close = previous = None
    for index, close, rows in ledgers:
        if previous is None or index != previous + 1:
            pending.clear()
            history = History()
            first_close = close
        while pending and pending[0][0] < close - WINDOW:
            expired, payments = pending.popleft()
            for payment in payments:
                history.update(expired, payment, -1)
        complete = close - first_close >= WINDOW
        for position, identity, sender, receiver, amount, fee in rows:
            values = (log1p(amount), log1p(fee))
            if complete:
                values += history.context(sender, receiver, close)
            yield index, position, identity, close, complete, values
        # Valid XRPL close times increase. Store enforces this before replay.
        for payment in rows:
            history.update(close, payment, 1)
        pending.append((close, rows))
        previous = index
