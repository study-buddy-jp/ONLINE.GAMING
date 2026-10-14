"""
Matchday Prediction model.
Builds team strength figures from finished matches and turns them into
probabilities with a Poisson model. Pure Python: no network calls here.
The caller passes in the finished matches it already fetched.
"""
import math
from collections import defaultdict

K_ELO = 20            # how fast ratings move after each match
HOME_ELO = 60         # rating points given to the home side for home advantage
BASE_ELO = 1500       # starting rating for a team with no history
DECAY = 0.97          # weight of older matches, per match back in time (recency)
MAX_GOALS = 7         # Poisson grid size


def _score(match):
    """Return (home_goals, away_goals) or None if the match has no final score."""
    ft = (match.get("score") or {}).get("fullTime") or {}
    hg, ag = ft.get("home"), ft.get("away")
    if hg is None or ag is None:
        return None
    return hg, ag


def build_ratings(matches):
    """
    matches: finished matches for ONE league, oldest first.
    Returns a dict: team_id -> stats used for prediction.
    """
    elo = defaultdict(lambda: BASE_ELO)
    stats = defaultdict(lambda: {
        "name": "", "n": 0,
        "home_for": 0.0, "home_against": 0.0, "home_w": 0.0,
        "away_for": 0.0, "away_against": 0.0, "away_w": 0.0,
        "last_date": None,
    })
    league_home_goals = league_away_goals = league_games = 0.0

    for m in matches:
        sc = _score(m)
        if sc is None:
            continue
        hg, ag = sc
        h_id, a_id = m["homeTeam"]["id"], m["awayTeam"]["id"]
        stats[h_id]["name"] = m["homeTeam"]["name"]
        stats[a_id]["name"] = m["awayTeam"]["name"]

        # Elo update, with home advantage added to the home side
        r_h = elo[h_id] + HOME_ELO
        r_a = elo[a_id]
        exp_h = 1 / (1 + 10 ** ((r_a - r_h) / 400))
        res_h = 1.0 if hg > ag else (0.5 if hg == ag else 0.0)
        goal_mult = 1 + min(abs(hg - ag), 3) * 0.1   # bigger wins move ratings more
        delta = K_ELO * goal_mult * (res_h - exp_h)
        elo[h_id] += delta
        elo[a_id] -= delta

        # Per-side goal records
        s_h, s_a = stats[h_id], stats[a_id]
        s_h["n"] += 1
        s_a["n"] += 1
        s_h["home_for"] += hg; s_h["home_against"] += ag; s_h["home_w"] += 1
        s_a["away_for"] += ag; s_a["away_against"] += hg; s_a["away_w"] += 1
        s_h["last_date"] = m["utcDate"]
        s_a["last_date"] = m["utcDate"]

        league_home_goals += hg
        league_away_goals += ag
        league_games += 1

    league_avg_home = league_home_goals / league_games if league_games else 1.35
    league_avg_away = league_away_goals / league_games if league_games else 1.10

    result = {}
    for t_id, s in stats.items():
        hw = s["home_w"] or 1
        aw = s["away_w"] or 1
        result[t_id] = {
            "name": s["name"],
            "elo": round(elo[t_id], 1),
            "attack_home": (s["home_for"] / hw) / league_avg_home,
            "defence_home": (s["home_against"] / hw) / league_avg_away,
            "attack_away": (s["away_for"] / aw) / league_avg_away,
            "defence_away": (s["away_against"] / aw) / league_avg_home,
            "league_home": league_avg_home,
            "league_away": league_avg_away,
            "games": s["n"],
            "last_date": s["last_date"],
        }
    return result


def expected_goals(home, away):
    """Expected goals for each side, from strengths and league averages."""
    xg_home = home["attack_home"] * away["defence_away"] * home["league_home"]
    xg_away = away["attack_away"] * home["defence_home"] * home["league_away"]
    return xg_home, xg_away


def poisson_p(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def match_probs(xg_home, xg_away, max_goals=MAX_GOALS):
    """Home win, draw, away win as percentages that add to 100."""
    home_w = draw = away_w = 0.0
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = poisson_p(h, xg_home) * poisson_p(a, xg_away)
            if h > a:
                home_w += p
            elif h == a:
                draw += p
            else:
                away_w += p
    total = home_w + draw + away_w
    return (round(home_w / total * 100, 1),
            round(draw / total * 100, 1),
            round(away_w / total * 100, 1))


def predict(matches, home_id, away_id):
    """
    One call for the app. Returns a dict with the figures and probabilities,
    or None if either team has no history in the matches supplied.
    """
    ratings = build_ratings(matches)
    if home_id not in ratings or away_id not in ratings:
        return None
    h, a = ratings[home_id], ratings[away_id]
    xg_h, xg_a = expected_goals(h, a)
    elo_home = 1 / (1 + 10 ** ((a["elo"] - (h["elo"] + HOME_ELO)) / 400))
    p_home, p_draw, p_away = match_probs(xg_h, xg_a)
    return {
        "home": h["name"], "away": a["name"],
        "home_elo": h["elo"], "away_elo": a["elo"],
        "home_xg": round(xg_h, 2), "away_xg": round(xg_a, 2),
        "elo_home_pct": round(elo_home * 100, 1),
        "p_home": p_home, "p_draw": p_draw, "p_away": p_away,
    }
