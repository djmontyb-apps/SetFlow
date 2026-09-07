
import math
import random
import re
from dataclasses import dataclass

CAMELOT_RE = re.compile(r"^\s*(1[0-2]|[1-9])([AB])\s*$", re.I)

@dataclass
class Settings:
    key_weight: float = 0.60
    bpm_weight: float = 0.40
    bpm_tolerance: float = 4.0
    allow_half_double: bool = True
    energy_influence: float = 0.15
    artist_spacing: float = 0.08
    energy_mode: str = "Smooth"   # Smooth | Build
    depth: str = "Standard"       # Quick | Standard | Deep
    lock_first: bool = False
    lock_last: bool = False
    seed: int = 42

def parse_camelot(value):
    if value is None:
        return None
    m = CAMELOT_RE.match(str(value))
    if not m:
        return None
    return int(m.group(1)), m.group(2).upper()

def wheel_distance(a, b):
    d = abs(a - b)
    return min(d, 12 - d)

def key_score(k1, k2):
    """0..1 score based on practical Camelot-wheel relationships."""
    a = parse_camelot(k1)
    b = parse_camelot(k2)
    if not a or not b:
        return 0.50
    n1, l1 = a
    n2, l2 = b
    d = wheel_distance(n1, n2)

    if n1 == n2 and l1 == l2:
        return 1.00                     # same key
    if n1 == n2 and l1 != l2:
        return 0.96                     # relative major/minor
    if d == 1 and l1 == l2:
        return 0.94                     # Camelot +/-1
    if d == 1 and l1 != l2:
        return 0.78                     # diagonal neighbor
    if d == 2 and l1 == l2:
        return 0.64                     # usable stretch
    if d == 2 and l1 != l2:
        return 0.48
    return max(0.12, 0.38 - 0.06 * min(d, 4))

def effective_bpm_pair(b1, b2, allow_half_double=True):
    """Return the equivalent BPM pair with the smallest practical difference."""
    try:
        b1, b2 = float(b1), float(b2)
    except Exception:
        return None, None, 999.0

    if not allow_half_double:
        return b1, b2, abs(b1 - b2)

    choices = []
    for f1 in (0.5, 1.0, 2.0):
        for f2 in (0.5, 1.0, 2.0):
            x, y = b1 * f1, b2 * f2
            # Keep comparisons in a plausible DJ tempo range.
            if 60 <= x <= 160 and 60 <= y <= 160:
                choices.append((x, y, abs(x-y)))
    if not choices:
        return b1, b2, abs(b1-b2)
    return min(choices, key=lambda t: t[2])

def bpm_score(b1, b2, tolerance=4.0, allow_half_double=True):
    x, y, d = effective_bpm_pair(b1, b2, allow_half_double)
    if d >= 999:
        return 0.50, d, x, y
    t = max(float(tolerance), 0.5)
    if d <= t:
        score = 1.0 - 0.20 * (d / t)
    elif d <= 2*t:
        score = 0.80 - 0.45 * ((d-t)/t)
    elif d <= 3*t:
        score = 0.35 - 0.30 * ((d-2*t)/t)
    else:
        score = max(0.0, 0.05 - 0.01*(d-3*t))
    return max(0.0, min(1.0, score)), d, x, y

def energy_score(e1, e2, mode="Smooth"):
    try:
        e1, e2 = float(e1), float(e2)
    except Exception:
        return 0.50
    delta = e2 - e1
    if mode == "Build":
        # Favor modest rises, tolerate modest dips, punish sharp drops.
        if 0 <= delta <= 8:
            return 1.0
        if 8 < delta <= 18:
            return 0.82
        if -5 <= delta < 0:
            return 0.78
        if -12 <= delta < -5:
            return 0.48
        return max(0.12, 0.55 - abs(delta)/60.0)
    # Smooth
    d = abs(delta)
    if d <= 5: return 1.0
    if d <= 10: return 0.85
    if d <= 20: return 0.60
    return max(0.15, 0.60 - (d-20)/70.0)

def transition_score(a, b, s: Settings):
    ks = key_score(a.get("Camelot Key"), b.get("Camelot Key"))
    bs, bpm_diff, eb1, eb2 = bpm_score(
        a.get("BPM"), b.get("BPM"), s.bpm_tolerance, s.allow_half_double
    )

    primary_total = max(s.key_weight + s.bpm_weight, 0.0001)
    primary = (ks*s.key_weight + bs*s.bpm_weight) / primary_total

    es = energy_score(a.get("Energy"), b.get("Energy"), s.energy_mode)
    score = primary * (1.0 - s.energy_influence) + es * s.energy_influence

    same_artist = (
        str(a.get("Artist","")).strip().lower()
        and str(a.get("Artist","")).strip().lower() == str(b.get("Artist","")).strip().lower()
    )
    if same_artist:
        score -= s.artist_spacing

    score = max(0.0, min(1.0, score))
    return score, {
        "score": round(score*100, 1),
        "key_score": round(ks*100, 1),
        "bpm_score": round(bs*100, 1),
        "energy_score": round(es*100, 1),
        "bpm_diff": round(bpm_diff, 2) if bpm_diff < 999 else None,
        "effective_bpm_from": round(eb1, 2) if eb1 is not None else None,
        "effective_bpm_to": round(eb2, 2) if eb2 is not None else None,
        "same_artist": bool(same_artist),
    }

def playlist_score(order, s):
    if len(order) < 2:
        return 0.0
    return sum(transition_score(order[i], order[i+1], s)[0] for i in range(len(order)-1))

def greedy_order(tracks, s, start_index=None):
    n = len(tracks)
    if n <= 2:
        return list(tracks)

    remaining = list(range(n))
    if s.lock_first:
        current = 0
    elif start_index is not None:
        current = start_index
    else:
        # Automatic opener: lower-half energy and good connectivity.
        energies = [float(t.get("Energy",50) or 50) for t in tracks]
        median = sorted(energies)[len(energies)//2]
        candidates = [i for i,e in enumerate(energies) if e <= median] or remaining
        current = max(
            candidates,
            key=lambda i: sum(transition_score(tracks[i], tracks[j], s)[0] for j in remaining if j != i)
        )

    order_idx = [current]
    remaining.remove(current)

    locked_last_idx = n-1 if s.lock_last and (n-1) in remaining else None
    if locked_last_idx is not None:
        remaining.remove(locked_last_idx)

    while remaining:
        cur = tracks[order_idx[-1]]
        nxt = max(remaining, key=lambda j: transition_score(cur, tracks[j], s)[0])
        order_idx.append(nxt)
        remaining.remove(nxt)

    if locked_last_idx is not None:
        order_idx.append(locked_last_idx)

    return [tracks[i] for i in order_idx]

def improve_by_swaps(order, s, iterations=1200):
    rng = random.Random(s.seed)
    best = list(order)
    best_score = playlist_score(best, s)
    n = len(best)
    if n < 4:
        return best

    movable = list(range(n))
    if s.lock_first and 0 in movable:
        movable.remove(0)
    if s.lock_last and n-1 in movable:
        movable.remove(n-1)

    if len(movable) < 2:
        return best

    for _ in range(iterations):
        i, j = sorted(rng.sample(movable, 2))
        cand = list(best)
        cand[i], cand[j] = cand[j], cand[i]
        sc = playlist_score(cand, s)
        if sc > best_score:
            best, best_score = cand, sc
    return best

def optimize(tracks, s: Settings):
    if not tracks:
        return [], []

    # Multiple greedy starts make the search much stronger without brute force.
    if s.depth == "Quick":
        starts = [None]
        swaps = 0
    elif s.depth == "Deep":
        starts = list(range(min(len(tracks), 12)))
        swaps = 6000
    else:
        starts = [None] + list(range(min(len(tracks), 5)))
        swaps = 1800

    candidates = []
    for st in starts:
        if s.lock_first and st not in (None, 0):
            continue
        o = greedy_order(tracks, s, st)
        if swaps:
            o = improve_by_swaps(o, s, swaps)
        candidates.append(o)

    best = max(candidates, key=lambda o: playlist_score(o, s))

    transitions = []
    for i in range(len(best)-1):
        _, detail = transition_score(best[i], best[i+1], s)
        transitions.append(detail)
    return best, transitions
