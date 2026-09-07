import math
import random
import re
from dataclasses import dataclass

CAMELOT_RE = re.compile(r"^\s*(1[0-2]|[1-9])([AB])\s*$", re.I)


@dataclass
class Settings:
    # BPM is a guardrail in v0.2. key_weight is preference *inside* a mixable tempo zone.
    key_weight: float = 0.60
    bpm_weight: float = 0.40
    bpm_tolerance: float = 4.0
    bpm_guardrail: float = 8.0
    allow_half_double: bool = True
    escape_mode: bool = True
    min_transition_target: float = 60.0
    energy_influence: float = 0.15
    artist_spacing: float = 0.08
    energy_mode: str = "Smooth"   # Smooth | Build (adjacent-track behavior)
    # v0.6 Programming Brain: shape the whole set using Energy metadata while
    # keeping BPM safety lexicographically more important than programming.
    energy_arc: str = "Party Arc"  # Off | Smooth | Build | Party Arc
    energy_arc_influence: float = 0.25
    depth: str = "Standard"       # Quick | Standard | Deep
    lock_first: bool = False
    lock_last: bool = False
    seed: int = 42
    # v0.3: whole-set rescue controls. Bad links matter more than small average gains.
    rescue_passes: int = 6
    # v0.4: plan around tempo outliers before building the easy middle.
    anchor_neighbor_count: int = 2
    # v0.5: build a BPM spine candidate so tempo islands are connected before
    # harmonic optimization. This prevents the optimizer from spending every
    # useful bridge and leaving a 15-40 BPM cliff near the end.
    bpm_spine: bool = True


def parse_camelot(value):
    if value is None:
        return None
    m = CAMELOT_RE.match(str(value))
    if not m:
        return None
    return int(m.group(1)), m.group(2).upper()


def _cw_delta(n1, n2):
    return (n2 - n1) % 12


def camelot_relationship(k1, k2):
    """Return (label, score 0..1) using SetFlow's practical DJ rules."""
    a = parse_camelot(k1)
    b = parse_camelot(k2)
    if not a or not b:
        return "Unknown key", 0.50

    n1, l1 = a
    n2, l2 = b

    if n1 == n2 and l1 == l2:
        return "Perfect Match", 1.00
    if n1 == n2 and l1 != l2:
        return "Relative Major/Minor", 0.97

    if l1 == l2:
        d = _cw_delta(n1, n2)
        if d == 1:
            return "Adjacent +1", 0.95
        if d == 11:
            return "Adjacent -1", 0.95
        if d == 2:
            return "Energy Lift +2", 0.88
        if d == 10:
            return "Energy Drop -2", 0.88
        if d == 7:
            return "Peak Surge +7", 0.76
        if d == 5:
            return "Deep Drop -7", 0.76
        # Other same-letter relationships get some credit but are not preferred.
        wheel_dist = min(d, 12 - d)
        return "Other Camelot", max(0.24, 0.52 - 0.06 * wheel_dist)

    # Opposite letter, different number: generally not a core SetFlow rule.
    wheel_dist = min(abs(n1 - n2), 12 - abs(n1 - n2))
    if wheel_dist == 1:
        return "Diagonal Key", 0.58
    return "Key Mismatch", max(0.15, 0.36 - 0.04 * min(wheel_dist, 4))


def key_score(k1, k2):
    return camelot_relationship(k1, k2)[1]


def _valid_bpm(value):
    try:
        x = float(value)
        return x if math.isfinite(x) and x > 0 else None
    except Exception:
        return None


def effective_bpm_pair(b1, b2, allow_half_double=True):
    """Return the practical equivalent BPM pair with the smallest difference.

    Half/double matching is only applied as a real 2:1 interpretation, and
    comparisons are kept in a normal DJ working range. This catches 179≈89.5
    without inventing arbitrary tempo mappings.
    """
    b1 = _valid_bpm(b1)
    b2 = _valid_bpm(b2)
    if b1 is None or b2 is None:
        return None, None, 999.0, "Unknown BPM"

    choices = [(b1, b2, abs(b1 - b2), "Normal")]
    if allow_half_double:
        # Normalize only one side at a time. This is enough for true half/double
        # relationships and avoids meaningless simultaneous scaling.
        candidates = [
            (b1 / 2.0, b2, "Half-time from"),
            (b1 * 2.0, b2, "Double-time from"),
            (b1, b2 / 2.0, "Half-time to"),
            (b1, b2 * 2.0, "Double-time to"),
        ]
        for x, y, label in candidates:
            if 60 <= x <= 160 and 60 <= y <= 160:
                # Only accept a half/double interpretation if the original tempos
                # plausibly represent the same pulse family (roughly 1.7x–2.3x).
                ratio = max(b1, b2) / max(min(b1, b2), 0.001)
                if 1.70 <= ratio <= 2.30:
                    choices.append((x, y, abs(x - y), label))

    x, y, d, label = min(choices, key=lambda t: t[2])
    return x, y, d, label


def bpm_mixability(b1, b2, tolerance=4.0, guardrail=8.0, allow_half_double=True):
    x, y, d, tempo_mode = effective_bpm_pair(b1, b2, allow_half_double)
    if d >= 999:
        return 0.50, d, x, y, tempo_mode, "Unknown BPM"

    t = max(float(tolerance), 0.5)
    g = max(float(guardrail), t + 1.0)

    if d <= t:
        score = 1.00 - 0.12 * (d / t)
        zone = "Mixable"
    elif d <= g:
        frac = (d - t) / max(g - t, 0.5)
        score = 0.88 - 0.43 * frac
        zone = "Stretch"
    elif d <= g + 4:
        frac = (d - g) / 4.0
        score = 0.32 - 0.22 * frac
        zone = "Hard BPM Jump"
    else:
        score = max(0.0, 0.08 - 0.005 * (d - g - 4))
        zone = "BPM Incompatible"

    return max(0.0, min(1.0, score)), d, x, y, tempo_mode, zone


def _clean_energy(value):
    try:
        x = float(value)
        # Spotify-like energy is normally 0..100 in our spreadsheets. Zero is
        # treated as missing because it frequently represents absent metadata.
        if not math.isfinite(x) or x <= 0 or x > 100:
            return None
        return x
    except Exception:
        return None


def energy_score(e1, e2, mode="Smooth"):
    e1 = _clean_energy(e1)
    e2 = _clean_energy(e2)
    if e1 is None or e2 is None:
        return 0.70, True

    delta = e2 - e1
    if mode == "Build":
        if 0 <= delta <= 8:
            return 1.00, False
        if 8 < delta <= 18:
            return 0.84, False
        if -5 <= delta < 0:
            return 0.78, False
        if -12 <= delta < -5:
            return 0.50, False
        return max(0.15, 0.58 - abs(delta) / 65.0), False

    d = abs(delta)
    if d <= 5:
        return 1.00, False
    if d <= 10:
        return 0.86, False
    if d <= 20:
        return 0.62, False
    return max(0.18, 0.62 - (d - 20) / 75.0), False


def transition_score(a, b, s: Settings, force_escape=False):
    relation, ks = camelot_relationship(a.get("Camelot Key"), b.get("Camelot Key"))
    bs, bpm_diff, eb1, eb2, tempo_mode, bpm_zone = bpm_mixability(
        a.get("BPM"), b.get("BPM"), s.bpm_tolerance, s.bpm_guardrail,
        s.allow_half_double
    )

    # Inside a sensible tempo zone, key/BPM preference behaves like the v0.1
    # slider. Outside it, the BPM guardrail caps what harmony can rescue.
    primary_total = max(s.key_weight + s.bpm_weight, 0.0001)
    harmonic_mix = (ks * s.key_weight + bs * s.bpm_weight) / primary_total

    if bpm_diff < 999 and bpm_diff > s.bpm_guardrail:
        # A perfect Camelot match cannot turn a 30 BPM jump into a good blend.
        bpm_cap = 0.48 if bpm_diff <= s.bpm_guardrail + 4 else 0.32
        harmonic_mix = min(harmonic_mix, bpm_cap)

    es, energy_missing = energy_score(a.get("Energy"), b.get("Energy"), s.energy_mode)
    score = harmonic_mix * (1.0 - s.energy_influence) + es * s.energy_influence

    artist_a = str(a.get("Artist", "")).strip().lower()
    artist_b = str(b.get("Artist", "")).strip().lower()
    same_artist = bool(artist_a and artist_a == artist_b)
    if same_artist:
        score -= s.artist_spacing

    score = max(0.0, min(1.0, score))

    # Human-readable reason for the actual DJ decision.
    if force_escape:
        reason = "BPM Escape"
    elif bpm_zone in ("BPM Incompatible", "Hard BPM Jump"):
        reason = bpm_zone
    elif tempo_mode != "Normal" and bpm_diff <= s.bpm_tolerance:
        reason = "Half/Double Tempo Match"
    elif relation in ("Perfect Match", "Relative Major/Minor", "Adjacent +1", "Adjacent -1"):
        reason = relation
    elif relation.startswith("Energy Lift"):
        reason = "Energy Lift"
    elif relation.startswith("Energy Drop"):
        reason = "Energy Drop"
    elif relation.startswith("Peak Surge"):
        reason = "Peak Surge"
    elif relation.startswith("Deep Drop"):
        reason = "Deep Drop"
    elif bpm_diff <= s.bpm_tolerance:
        reason = "BPM First"
    else:
        reason = relation

    return score, {
        "score": round(score * 100, 1),
        "reason": reason,
        "camelot_relationship": relation,
        "key_score": round(ks * 100, 1),
        "bpm_score": round(bs * 100, 1),
        "energy_score": round(es * 100, 1),
        "bpm_diff": round(bpm_diff, 2) if bpm_diff < 999 else None,
        "effective_bpm_from": round(eb1, 2) if eb1 is not None else None,
        "effective_bpm_to": round(eb2, 2) if eb2 is not None else None,
        "tempo_mode": tempo_mode,
        "bpm_zone": bpm_zone,
        "same_artist": same_artist,
        "energy_missing": energy_missing,
        "escape": bool(force_escape),
    }


def _edge(order, i, j, s):
    return transition_score(order[i], order[j], s)[0]



def _energy_values(order):
    vals = [_clean_energy(t.get("Energy")) for t in order]
    usable = [v for v in vals if v is not None]
    if not usable:
        return [50.0] * len(order), True
    usable_sorted = sorted(usable)
    median = usable_sorted[len(usable_sorted)//2]
    return [median if v is None else v for v in vals], any(v is None for v in vals)


def _quantile(sorted_vals, q):
    if not sorted_vals:
        return 50.0
    q = max(0.0, min(1.0, float(q)))
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_vals[lo])
    f = pos - lo
    return float(sorted_vals[lo] * (1-f) + sorted_vals[hi] * f)


def energy_arc_score(order, s):
    """Score how well the whole running order follows the selected energy arc.

    This is intentionally a *programming* score, not a transition-safety score.
    It uses the playlist's own energy distribution, so a Salsa set and a House
    set can both build naturally without hard-coded universal Energy numbers.
    Missing/suspicious Energy values are filled with the playlist median.
    """
    if len(order) < 2 or getattr(s, "energy_arc", "Off") == "Off":
        return 1.0
    vals, _ = _energy_values(order)
    sorted_vals = sorted(vals)
    n = len(vals)
    errors = []
    mode = getattr(s, "energy_arc", "Party Arc")

    for i, actual in enumerate(vals):
        x = i / max(n - 1, 1)
        if mode == "Build":
            # Low-ish opener to high-energy closer.
            q = 0.20 + 0.75 * x
        elif mode == "Smooth":
            # Gentle rise through the night, avoiding a rigid climb.
            q = 0.38 + 0.24 * x
        else:  # Party Arc
            # Warm-up -> steady build -> peak around 75% -> ease down to a
            # still-positive finish. Piecewise quantile path, not fixed values.
            if x <= 0.75:
                q = 0.20 + (0.78 * (x / 0.75))
            else:
                q = 0.98 - (0.38 * ((x - 0.75) / 0.25))
        target = _quantile(sorted_vals, q)
        errors.append(abs(actual - target))

    mae = sum(errors) / len(errors)
    # 0 error = 1.0. A 25-point average miss is already a poor programming arc.
    return max(0.0, 1.0 - mae / 25.0)


def energy_arc_details(order, s):
    vals, had_missing = _energy_values(order)
    score = energy_arc_score(order, s)
    if not vals:
        return {"score": 100.0, "start": None, "peak": None, "finish": None, "missing": had_missing}
    peak_i = max(range(len(vals)), key=lambda i: vals[i])
    return {
        "score": round(score * 100, 1),
        "start": round(vals[0], 1),
        "peak": round(max(vals), 1),
        "peak_position": peak_i + 1,
        "finish": round(vals[-1], 1),
        "missing": had_missing,
    }


def objective(order, s):
    """v0.3 whole-set objective: protect the weakest links first.

    A route with one disastrous transition should lose to a route with slightly
    lower average scores but no disaster. This is the anti-garbage-pile rule.
    """
    if len(order) < 2:
        return (0, 0, 0.0, 0.0, 0.0)
    scores = []
    severe = 0
    hard = 0
    weak = 0
    pain = 0.0
    for i in range(len(order) - 1):
        sc, d = transition_score(order[i], order[i + 1], s)
        pct = sc * 100
        scores.append(sc)
        bpm_diff = d["bpm_diff"]
        if bpm_diff is not None and bpm_diff > s.bpm_guardrail:
            hard += 1
            # Any guardrail violation is a route-planning failure in v0.5.
            # The penalty rises quickly so a 10-12 BPM cliff is not accepted
            # merely because the rest of the route has prettier Camelot scores.
            pain += (bpm_diff - s.bpm_guardrail) ** 2 * 2.0
        if bpm_diff is not None and bpm_diff > s.bpm_guardrail + 4:
            severe += 1
            pain += (bpm_diff - (s.bpm_guardrail + 4)) ** 2 * 4.0
        if pct < s.min_transition_target:
            weak += 1
            pain += (s.min_transition_target - pct) ** 2 / 25.0
    # v0.6 lexicographic priority:
    # catastrophic cliffs -> any guardrail violation -> weak links -> pain ->
    # whole-set Energy Arc -> weakest edge -> total transition quality.
    # Programming can improve a safe route, but it can never justify a BPM cliff.
    arc = energy_arc_score(order, s)
    arc_weight = max(0.0, min(1.0, getattr(s, "energy_arc_influence", 0.25)))
    # Keep the arc term bounded so it refines rather than overwhelms mixing quality.
    programmed = arc * arc_weight + (sum(scores) / len(scores)) * (1.0 - arc_weight)
    return (-severe, -hard, -weak, -pain, programmed, min(scores), sum(scores))

def _connectivity(tracks, idx, s):
    """How many tempo-practical neighbors does this track have? Lower = orphan."""
    count = 0
    quality = 0.0
    for j in range(len(tracks)):
        if j == idx:
            continue
        _, d = transition_score(tracks[idx], tracks[j], s)
        if d["bpm_diff"] is None:
            continue
        if d["bpm_diff"] <= s.bpm_guardrail:
            count += 1
            quality += max(0.0, 1.0 - d["bpm_diff"] / max(s.bpm_guardrail, 1.0))
    return count, quality


def _choose_next(cur_idx, remaining, tracks, s, connectivity):
    """Greedy step with orphan awareness and Escape Mode."""
    normal = []
    for j in remaining:
        sc, d = transition_score(tracks[cur_idx], tracks[j], s)
        normal.append((j, sc, d))

    safe = [x for x in normal if x[2]["bpm_diff"] is None or x[2]["bpm_diff"] <= s.bpm_guardrail]
    harmonic_safe = [x for x in safe if x[2]["key_score"] >= 70]

    pool = harmonic_safe or safe
    escape = False
    if not pool:
        pool = normal
        escape = bool(s.escape_mode)

    # Prefer a strong immediate transition, but also avoid leaving low-degree
    # tracks until the end. The orphan bonus is gentle and only breaks close calls.
    def utility(item):
        j, sc, d = item
        degree = connectivity[j][0]
        orphan_bonus = 0.045 / (1.0 + degree)
        bpm_bonus = 0.0
        if escape and d["bpm_diff"] is not None:
            bpm_bonus = max(0.0, 0.08 - 0.008 * d["bpm_diff"])
        return sc + orphan_bonus + bpm_bonus

    chosen = max(pool, key=utility)
    return chosen[0], escape


def greedy_order(tracks, s, start_index=None):
    n = len(tracks)
    if n <= 2:
        return list(tracks)

    connectivity = [_connectivity(tracks, i, s) for i in range(n)]
    remaining = list(range(n))

    if s.lock_first:
        current = 0
    elif start_index is not None:
        current = start_index
    else:
        # Automatic opener: prefer a well-connected, lower-energy track.
        valid_energies = [_clean_energy(t.get("Energy")) for t in tracks]
        usable = [e for e in valid_energies if e is not None]
        median = sorted(usable)[len(usable) // 2] if usable else 50
        candidates = [i for i, e in enumerate(valid_energies) if e is None or e <= median] or remaining
        current = max(candidates, key=lambda i: (connectivity[i][0], connectivity[i][1]))

    order_idx = [current]
    remaining.remove(current)

    locked_last_idx = n - 1 if s.lock_last and (n - 1) in remaining else None
    if locked_last_idx is not None:
        remaining.remove(locked_last_idx)

    while remaining:
        nxt, _ = _choose_next(order_idx[-1], remaining, tracks, s, connectivity)
        order_idx.append(nxt)
        remaining.remove(nxt)

    if locked_last_idx is not None:
        order_idx.append(locked_last_idx)

    return [tracks[i] for i in order_idx]


def transition_quality(detail, s):
    """Human DJ-oriented quality label for a finished transition."""
    score = float(detail.get("score", 0))
    diff = detail.get("bpm_diff")
    zone = detail.get("bpm_zone")
    if zone == "BPM Incompatible" or (diff is not None and diff > s.bpm_guardrail + 4):
        return "Weak"
    if detail.get("reason") == "BPM Escape":
        return "BPM Escape"
    if score >= 90:
        return "Excellent"
    if score >= 80:
        return "Good"
    if score >= s.min_transition_target:
        return "DJ Workable"
    return "Weak"


def anchor_first_order(tracks, s):
    """v0.4 route builder: reserve practical neighbors for tempo islands first.

    The hard-to-place tracks are handled before the easy, highly connected tracks.
    For each anchor we reserve its best unused BPM-practical neighbor, creating
    small blocks. Blocks are then merged by the best whole-set objective rather
    than allowing the easy middle of the playlist to consume all useful bridges.
    """
    n = len(tracks)
    if n <= 2:
        return list(tracks)

    conn = [_connectivity(tracks, i, s) for i in range(n)]
    # Lowest practical degree first; quality breaks ties.
    anchors = sorted(range(n), key=lambda i: (conn[i][0], conn[i][1]))
    unused = set(range(n))
    blocks = []

    def pair_value(i, j):
        sc, d = transition_score(tracks[i], tracks[j], s)
        diff = d["bpm_diff"] if d["bpm_diff"] is not None else 999.0
        # BPM practicality dominates reservation; harmony breaks close calls.
        practical = 1 if diff <= s.bpm_guardrail else 0
        return (practical, -diff, sc)

    for a in anchors:
        if a not in unused:
            continue
        unused.remove(a)
        candidates = [j for j in unused]
        if not candidates:
            blocks.append([a])
            continue
        best = max(candidates, key=lambda j: pair_value(a, j))
        _, d = transition_score(tracks[a], tracks[best], s)
        # Reserve a neighbor only if it is genuinely useful. Otherwise leave the
        # anchor single so cluster merging can find the least-bad bridge globally.
        if d["bpm_diff"] is not None and d["bpm_diff"] <= s.bpm_guardrail + 4:
            unused.remove(best)
            # Choose direction that leaves the more connected endpoint outward.
            ab = [a, best]
            ba = [best, a]
            blocks.append(max((ab, ba), key=lambda b: objective([tracks[x] for x in b], s)))
        else:
            blocks.append([a])

    for i in sorted(unused):
        blocks.append([i])

    # Respect locked opener/closer by separating those singleton constraints.
    if s.lock_first:
        for b in list(blocks):
            if 0 in b:
                b.remove(0)
                if not b:
                    blocks.remove(b)
                break
        route = [0]
    else:
        # Begin with the most difficult block so it cannot become a tail orphan.
        seed_i = min(range(len(blocks)), key=lambda bi: min((conn[x][0], conn[x][1]) for x in blocks[bi]))
        route = blocks.pop(seed_i)

    locked_last = n - 1 if s.lock_last else None
    if locked_last is not None:
        for b in list(blocks):
            if locked_last in b:
                b.remove(locked_last)
                if not b:
                    blocks.remove(b)
                break

    # Merge one block at a time. Try both orientations and every insertion point;
    # evaluate the complete partial route with worst-link-first objective.
    while blocks:
        best_choice = None
        best_obj = None
        for bi, block in enumerate(blocks):
            orientations = [block] if len(block) == 1 else [block, list(reversed(block))]
            for orient in orientations:
                lo = 1 if s.lock_first else 0
                for pos in range(lo, len(route) + 1):
                    cand = route[:pos] + orient + route[pos:]
                    obj = objective([tracks[x] for x in cand], s)
                    if best_obj is None or obj > best_obj:
                        best_obj = obj
                        best_choice = (bi, cand)
        bi, route = best_choice
        blocks.pop(bi)

    if locked_last is not None:
        route = [x for x in route if x != locked_last] + [locked_last]
    return [tracks[i] for i in route]



def canonical_bpm(track):
    """Return a practical one-number BPM for whole-playlist geography.

    This is *not* used to score the final transition. It only helps SetFlow
    build a safe backbone. High double-time values are folded once when that
    lands them in the normal DJ working range. Pair scoring still uses
    effective_bpm_pair(), so the final math remains transition-specific.
    """
    b = _valid_bpm(track.get("BPM"))
    if b is None:
        return None
    if b >= 160 and 60 <= b / 2.0 <= 160:
        return b / 2.0
    return b


def bpm_spine_order(tracks, s):
    """v0.5 bridge planner: create a tempo-safe backbone, then polish it.

    The v0.4 anchor-first route could still consume a crucial bridge and later
    create a huge cliff (for example 121 -> 104). The BPM spine gives the
    optimizer at least one candidate whose whole route follows the tempo
    landscape. Because objective() treats severe BPM cliffs lexicographically,
    local optimization can improve harmony without re-introducing a disaster.
    """
    if len(tracks) <= 2:
        return list(tracks)

    known = []
    unknown = []
    for i, t in enumerate(tracks):
        cb = canonical_bpm(t)
        (known if cb is not None else unknown).append((i, cb))

    # If BPM is mostly unavailable, this candidate adds no value.
    if len(known) < 2:
        return list(tracks)

    asc_idx = [i for i, _ in sorted(known, key=lambda x: x[1])]
    desc_idx = list(reversed(asc_idx))

    # Place unknown-BPM tracks last in this *candidate*; other builders will
    # usually provide a better route when metadata is incomplete.
    unknown_idx = [i for i, _ in unknown]
    choices = [asc_idx + unknown_idx, desc_idx + unknown_idx]

    # Honor explicit locks without throwing away the rest of the spine.
    fixed = []
    for idxs in choices:
        route = list(idxs)
        if s.lock_first and 0 in route:
            route.remove(0)
            route.insert(0, 0)
        if s.lock_last and len(tracks) - 1 in route:
            last = len(tracks) - 1
            route.remove(last)
            route.append(last)
        fixed.append(route)

    return [tracks[i] for i in max(fixed, key=lambda idxs: objective([tracks[j] for j in idxs], s))]

def insertion_order(tracks, s):
    """Orphan-first cheapest insertion route to reduce end-of-playlist leftovers."""
    n = len(tracks)
    if n <= 2:
        return list(tracks)

    degrees = [_connectivity(tracks, i, s) for i in range(n)]
    indices = list(range(n))

    if s.lock_first:
        route = [0]
        pending = [i for i in indices if i != 0]
    else:
        # Start with the hardest-to-place track, then build a route around it.
        seed = min(indices, key=lambda i: (degrees[i][0], degrees[i][1]))
        route = [seed]
        pending = [i for i in indices if i != seed]

    locked_last = n - 1 if s.lock_last and (n - 1) in pending else None
    if locked_last is not None:
        pending.remove(locked_last)

    # Insert lower-connectivity tracks first.
    pending.sort(key=lambda i: (degrees[i][0], degrees[i][1]))

    for idx in pending:
        best_route = None
        best_obj = None
        lo = 1 if s.lock_first else 0
        hi = len(route) + 1
        for pos in range(lo, hi):
            cand = route[:pos] + [idx] + route[pos:]
            cand_tracks = [tracks[i] for i in cand]
            obj = objective(cand_tracks, s)
            if best_obj is None or obj > best_obj:
                best_obj = obj
                best_route = cand
        route = best_route

    if locked_last is not None:
        route.append(locked_last)

    return [tracks[i] for i in route]


def improve_local(order, s, iterations=1000):
    rng = random.Random(s.seed)
    best = list(order)
    best_obj = objective(best, s)
    n = len(best)
    if n < 4:
        return best

    movable = list(range(n))
    if s.lock_first and 0 in movable:
        movable.remove(0)
    if s.lock_last and n - 1 in movable:
        movable.remove(n - 1)
    if len(movable) < 2:
        return best

    for _ in range(iterations):
        cand = list(best)
        if rng.random() < 0.55:
            # Relocate is especially useful for moving an orphan into a BPM cluster.
            i, j = rng.sample(movable, 2)
            track = cand.pop(i)
            cand.insert(j, track)
        else:
            i, j = rng.sample(movable, 2)
            cand[i], cand[j] = cand[j], cand[i]

        obj = objective(cand, s)
        if obj > best_obj:
            best, best_obj = cand, obj
    return best


def rescue_weak_links(order, s):
    """Target the worst transitions with deterministic relocate/reverse moves.

    v0.2 could still optimize itself into a corner. v0.3 repeatedly identifies
    the weakest edge and tries moving either endpoint into every legal position.
    It also tries short segment reversals. Only whole-set improvements survive.
    """
    best = list(order)
    best_obj = objective(best, s)
    n = len(best)
    if n < 4:
        return best

    for _ in range(max(1, s.rescue_passes)):
        edge_info = []
        for i in range(n - 1):
            sc, d = transition_score(best[i], best[i + 1], s)
            bpm = d["bpm_diff"] if d["bpm_diff"] is not None else 0
            severity = (1 if bpm > s.bpm_guardrail + 4 else 0, -sc, bpm)
            edge_info.append((severity, i))
        # Work on several worst edges, not only the single worst one.
        worst_edges = [i for _, i in sorted(edge_info, reverse=True)[:min(6, len(edge_info))]]
        improved = False

        for edge_i in worst_edges:
            endpoints = [edge_i, edge_i + 1]
            for src in endpoints:
                if (s.lock_first and src == 0) or (s.lock_last and src == n - 1):
                    continue
                for dest in range(n):
                    if dest == src:
                        continue
                    if s.lock_first and dest == 0:
                        continue
                    if s.lock_last and dest >= n - 1:
                        continue
                    cand = list(best)
                    tr = cand.pop(src)
                    # dest is interpreted in the post-pop list.
                    dest2 = min(dest, len(cand))
                    cand.insert(dest2, tr)
                    obj = objective(cand, s)
                    if obj > best_obj:
                        best, best_obj = cand, obj
                        improved = True
                        break
                if improved:
                    break
            if improved:
                break

        if improved:
            continue

        # If relocation stalls, try reversing modest route segments.
        lo = 1 if s.lock_first else 0
        hi = n - 1 if s.lock_last else n
        for i in range(lo, hi - 2):
            for j in range(i + 2, min(hi, i + 10)):
                cand = best[:i] + list(reversed(best[i:j + 1])) + best[j + 1:]
                obj = objective(cand, s)
                if obj > best_obj:
                    best, best_obj = cand, obj
                    improved = True
                    break
            if improved:
                break
        if not improved:
            break
    return best



def _route_program_stats(order, s):
    severe = hard = weak = 0
    scores = []
    for i in range(len(order)-1):
        sc, d = transition_score(order[i], order[i+1], s)
        pct = sc * 100.0
        scores.append(pct)
        diff = d.get("bpm_diff")
        if diff is not None and diff > s.bpm_guardrail:
            hard += 1
        if diff is not None and diff > s.bpm_guardrail + 4:
            severe += 1
        if pct < s.min_transition_target:
            weak += 1
    return {
        "severe": severe, "hard": hard, "weak": weak,
        "avg": sum(scores)/max(len(scores),1),
        "minimum": min(scores) if scores else 100.0,
        "arc": energy_arc_score(order, s) * 100.0,
    }


def program_energy_arc(order, s):
    """v0.6 post-pass: improve whole-set Energy without breaking mixability.

    The Mixing Brain gets veto power. We only accept programming moves that keep
    the same counts of severe/hard/weak transitions, keep the average transition
    within a small budget, and improve the selected Energy Arc. This is a very
    DJ-like compromise: reshape the night *inside* safe BPM neighborhoods.
    """
    if getattr(s, "energy_arc", "Off") == "Off" or len(order) < 4:
        return list(order)
    best = list(order)
    base = _route_program_stats(best, s)
    # Higher influence permits a little more transition-score sacrifice.
    loss_budget = 0.75 + 5.0 * max(0.0, min(0.5, getattr(s, "energy_arc_influence", 0.25)))
    passes = 2 if s.depth == "Quick" else (5 if s.depth == "Standard" else 8)

    for _ in range(passes):
        best_move = None
        best_gain = 0.0
        n = len(best)
        lo = 1 if s.lock_first else 0
        hi = n-1 if s.lock_last else n

        # Swaps are ideal for energy programming because they can move a high
        # energy track later without changing the playlist membership or anchors.
        for i in range(lo, hi):
            for j in range(i+1, hi):
                cand = list(best)
                cand[i], cand[j] = cand[j], cand[i]
                st = _route_program_stats(cand, s)
                if (st["severe"], st["hard"], st["weak"]) != (base["severe"], base["hard"], base["weak"]):
                    continue
                if st["avg"] < base["avg"] - loss_budget:
                    continue
                gain = (st["arc"] - base["arc"]) + 0.15 * (st["avg"] - base["avg"])
                if gain > best_gain + 0.05:
                    best_gain = gain
                    best_move = (cand, st)

        if best_move is None:
            break
        best, base = best_move
    return best


def _mark_escape_reasons(order, transitions, s):
    """Label key-breaking but tempo-practical links as BPM Escape when appropriate."""
    if not s.escape_mode:
        return transitions
    out = []
    for i, d in enumerate(transitions):
        dd = dict(d)
        if (
            dd["bpm_diff"] is not None
            and dd["bpm_diff"] <= s.bpm_tolerance
            and dd["key_score"] < 55
            and dd["reason"] in ("BPM First", "Key Mismatch", "Other Camelot", "Diagonal Key")
        ):
            _, dd = transition_score(order[i], order[i + 1], s, force_escape=True)
        out.append(dd)
    return out


def optimize(tracks, s: Settings):
    if not tracks:
        return [], []

    n = len(tracks)
    if s.depth == "Quick":
        starts = [None]
        local_iters = min(300, 8 * n)
        use_insertion = False
    elif s.depth == "Deep":
        starts = [None] + list(range(min(n, 10)))
        local_iters = min(9000, max(2500, 35 * n))
        use_insertion = True
    else:
        starts = [None] + list(range(min(n, 5)))
        local_iters = min(3500, max(900, 18 * n))
        use_insertion = True

    candidates = [anchor_first_order(tracks, s)]
    if s.bpm_spine:
        candidates.append(bpm_spine_order(tracks, s))
    if use_insertion:
        candidates.append(insertion_order(tracks, s))

    for st in starts:
        if s.lock_first and st not in (None, 0):
            continue
        candidates.append(greedy_order(tracks, s, st))

    improved = []
    per_candidate = max(150, local_iters // max(len(candidates), 1))
    for idx, cand in enumerate(candidates):
        # Offset seed so candidates explore different local moves reproducibly.
        old_seed = s.seed
        s.seed = old_seed + idx * 97
        improved.append(improve_local(cand, s, per_candidate))
        s.seed = old_seed

    best = max(improved, key=lambda o: objective(o, s))
    # v0.3 rescue pass: explicitly repair the weakest links before finalizing.
    best = rescue_weak_links(best, s)
    # v0.6 Programming Brain: reshape the safe route around the selected Energy
    # Arc without re-introducing the BPM cliffs v0.5 eliminated.
    best = program_energy_arc(best, s)

    transitions = []
    for i in range(len(best) - 1):
        _, detail = transition_score(best[i], best[i + 1], s)
        transitions.append(detail)
    transitions = _mark_escape_reasons(best, transitions, s)
    for detail in transitions:
        detail["quality"] = transition_quality(detail, s)
    return best, transitions
