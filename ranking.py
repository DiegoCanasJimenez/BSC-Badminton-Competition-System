"""
ranking.py - how teams earn points and how the ranking table is made.

IMPORTANT (dynamic tournaments):
The ranking is NEVER stored. It is calculated again from the finished games
every time somebody opens the dashboard. That means:
  * new teams can be added at any moment, they simply start with 0 points;
  * old results are never lost, because they stay in the 'games' table;
  * if a score is corrected, the ranking is automatically correct too.
"""


def game_points(my_score, opponent_score):
    """
    The ranking calculator: how many ranking points a team gets for ONE game.

    Current rule (simple):
        win  = 2 points
        loss = 0 points

    This is the ONLY place where points are decided, so to change the
    ranking system you only have to change this function.

    IDEA for the future: base the points on the scores themselves, e.g. reward
    big wins more than close wins, or give the loser something for a close game:
        difference = my_score - opponent_score
        if difference > 0:
            return 2 + difference / 10      # winner gets a bonus for a big win
        else:
            return max(0, 1 + difference / 10)   # close loss still gives a little
    Or use a real Elo system, where beating a strong team gives more points
    than beating a weak team (that would need each team's current rating).
    """
    if my_score > opponent_score:
        return 2
    return 0


def build_ranking(teams, games):
    """
    Make the ranking, one list per league.

    teams : list of team rows (from the database)
    games : list of game rows (from the database)

    Returns a dictionary league_id -> list, like:
        { 7: [row, row, ...], 8: [...], 9: [...] }
    where every row is a dictionary with the team name, games played,
    wins, losses, points and point difference, sorted best team first.
    """
    # Step 1: an empty line in the ranking for every team
    lines = {}
    for team in teams:
        lines[team["team_id"]] = {
            "team_id": team["team_id"],
            "team_name": team["team_name"],
            "league_id": team["league_id"],
            "played": 0,
            "won": 0,
            "lost": 0,
            "points": 0,
            "points_scored": 0,
            "points_against": 0,
        }

    # Step 2: go through every finished game and add it to both teams
    for game in games:
        if not game["finished"]:
            continue
        team1 = game["team1_id"]
        team2 = game["team2_id"]
        if team1 not in lines or team2 not in lines:
            continue  # should not happen, but never crash the ranking
        score1 = game["score1"]
        score2 = game["score2"]

        add_game_to_line(lines[team1], score1, score2)
        add_game_to_line(lines[team2], score2, score1)

    # Step 3: split per league and sort
    ranking = {}
    for line in lines.values():
        line["difference"] = line["points_scored"] - line["points_against"]
        league_id = line["league_id"]
        if league_id not in ranking:
            ranking[league_id] = []
        ranking[league_id].append(line)

    for league_id in ranking:
        # Best first: most ranking points, then best point difference,
        # then the team name alphabetically.
        ranking[league_id].sort(key=sort_key_for_ranking)
        position = 1
        for line in ranking[league_id]:
            line["position"] = position
            position = position + 1

    return ranking


def add_game_to_line(line, my_score, opponent_score):
    """Add the result of one game to one team's ranking line."""
    line["played"] = line["played"] + 1
    line["points_scored"] = line["points_scored"] + my_score
    line["points_against"] = line["points_against"] + opponent_score
    line["points"] = line["points"] + game_points(my_score, opponent_score)
    if my_score > opponent_score:
        line["won"] = line["won"] + 1
    else:
        line["lost"] = line["lost"] + 1


def sort_key_for_ranking(line):
    """Used by sort(): minus signs make big numbers come first."""
    return (-line["points"], -line["difference"], line["team_name"].lower())
