"""Venue-neutral match model.

Uses only finished results. There is no home-advantage term anywhere:
the home and away side are treated exactly the same way. Venue facts
(the league's home and away record) are shown as data in app.py instead.

predict(matches, home_id, away_id) returns a dict, or None when either
team has too few finished matches to rate.
"""
import math

PRIOR_GAMES = 3      # a team's own results count fully only after a few matches; before that the league average is mixed in
ELO_START = 1500
ELO_K = 20
MAX_GOALS = 10       # Poisson grid size per side


def _results(matches):
    """(utcDate, home_id, home_name, away_id, away_name, home_goals, away_goals), oldest first."""
    out = []
    for m in matches:
        ft = (m.get("score") or {}).get("fullTime") or {}
        hg, ag = ft.get("home"), ft.get("away")
        if hg is None or ag is None:
            continue
        out.append((
            m.get("utcDate", ""),
            m["homeTeam"]["id"], m["homeTeam"]["name"],
            m["awayTeam"]["id"], m["awayTeam"]["name"],
            hg, ag,
        ))
    out.sort(key=lambda r: r[0])
    return out


def _elo(results):
    rating = {}
    for _, hid, _, aid, _, hg, ag in results:
        rh = rating.get(hid, ELO_START)
        ra = rating.get(aid, ELO_START)
        expected_h = 1 / (1 + 10 ** ((ra - rh) / 400))
        actual_h = 1.0 if hg > ag else (0.0 if hg < ag else 0.5)
        rating[hid] = rh + ELO_K * (actual_h - expected_h)
        rating[aid] = ra + ELO_K * ((1 - actual_h) - (1 - expected_h))
    return rating


def _strengths(results):
    """Attack and defence for each team, relative to the league average goals per team per match.
    Teams with few matches are pulled toward the average (1.0), so every team gets a rating,
    including one with no finished matches yet."""
    scored, conceded, played = {}, {}, {}
    total_goals = 0
    for _, hid, _, aid, _, hg, ag in results:
        for tid, gf, ga in ((hid, hg, ag), (aid, ag, hg)):
            scored[tid] = scored.get(tid, 0) + gf
            conceded[tid] = conceded.get(tid, 0) + ga
            played[tid] = played.get(tid, 0) + 1
        total_goals += hg + ag
    team_matches = 2 * len(results)
    mu = total_goals / team_matches if team_matches else 1.0
    attack, defence = {}, {}
    for t in played:
        n = played[t]
        attack[t] = ((scored[t] + PRIOR_GAMES * mu) / (n + PRIOR_GAMES)) / mu
        defence[t] = ((conceded[t] + PRIOR_GAMES * mu) / (n + PRIOR_GAMES)) / mu
    return attack, defence, played, mu


def _poisson(lam, k):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def predict(matches, home_id, away_id):
    results = _results(matches)
    attack, defence, played, mu = _strengths(results)
    # attack/defence default to the league average for a team with no finished matches yet
    attack.setdefault(home_id, 1.0)
    defence.setdefault(home_id, 1.0)
    attack.setdefault(away_id, 1.0)
    defence.setdefault(away_id, 1.0)

    names = {}
    for _, hid, hname, aid, aname, _, _ in results:
        names[hid] = hname
        names[aid] = aname

    # Expected goals: each side's attack against the other side's defence. No venue term.
    xg_home = attack[home_id] * defence[away_id] * mu
    xg_away = attack[away_id] * defence[home_id] * mu

    p_home = p_draw = p_away = 0.0
    for i in range(MAX_GOALS + 1):
        pi = _poisson(xg_home, i)
        for j in range(MAX_GOALS + 1):
            p = pi * _poisson(xg_away, j)
            if i > j:
                p_home += p
            elif i == j:
                p_draw += p
            else:
                p_away += p
    total = p_home + p_draw + p_away
    p_home, p_draw, p_away = p_home / total, p_draw / total, p_away / total

    ratings = _elo(results)
    r_home = ratings.get(home_id, ELO_START)
    r_away = ratings.get(away_id, ELO_START)
    elo_home = 1 / (1 + 10 ** ((r_away - r_home) / 400))

    return {
        "p_home": round(p_home * 100, 1),
        "p_draw": round(p_draw * 100, 1),
        "p_away": round(p_away * 100, 1),
        "home_elo": round(r_home),
        "away_elo": round(r_away),
        "elo_home_pct": round(elo_home * 100, 1),
        "home_xg": round(xg_home, 2),
        "away_xg": round(xg_away, 2),
        "home": names.get(home_id, ""),
        "away": names.get(away_id, ""),
        "home_games": played.get(home_id, 0),
        "away_games": played.get(away_id, 0),
    }
