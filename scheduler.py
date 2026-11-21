"""
scheduler.py - builds the "concept schedule".

A schedule is a list of games. Every game has:
    batch    : 1, 2, 3, ...  (all games of one batch are played at the same time)
    court    : 1, 2, 3, ...
    team1_id, team2_id, league_id

Rules we follow:
  1. A team never plays twice in the same batch.
  2. Teams only play against teams of their own league.
  3. Every team plays every other team of its league once.
  4. If repetition is allowed, free courts are filled with "extra" games
     between teams that already met. We pick the pairs that met the least,
     and the teams with the fewest games, so repetition stays minimal and fair.
  5. Games are spread as evenly as possible, so nobody waits very long.

How it works (simple version):
  * For every league we first make "rounds" with the classic circle method
    (in one round every team plays exactly once). This gives a nice, even order.
  * Then we fill the batches one by one. For each batch we take the games that
    are the "least far" in their league, and among those the teams that have
    been waiting the longest, until all courts are used.
"""


def pair_key(team_a, team_b):
    """
    Give back the pair with the smallest id first.
    This way (3, 7) and (7, 3) are seen as the same pair.
    """
    if team_a < team_b:
        return (team_a, team_b)
    return (team_b, team_a)


def round_robin_rounds(team_ids):
    """
    The classic "circle method" to make a round robin.

    Example with teams A B C D:
        round 1: A-D, B-C
        round 2: A-C, D-B
        round 3: A-B, C-D
    Every team plays once per round and everybody meets everybody once.
    With an odd number of teams we add an empty spot (None): the team
    that is paired with None sits out that round.
    """
    teams = list(team_ids)
    if len(teams) % 2 == 1:
        teams.append(None)

    number_of_spots = len(teams)
    rounds = []
    for round_number in range(number_of_spots - 1):
        games_in_round = []
        for i in range(number_of_spots // 2):
            team_a = teams[i]
            team_b = teams[number_of_spots - 1 - i]
            if team_a is not None and team_b is not None:
                games_in_round.append((team_a, team_b))
        rounds.append(games_in_round)

        # Rotate: the first team stays where it is, the last one moves to spot 2
        teams = [teams[0]] + [teams[-1]] + teams[1:-1]
    return rounds


def build_schedule(teams, number_of_courts, allow_repetition, first_batch=1, earlier_games=None):
    """
    Build the concept schedule.

    teams            : list with one dictionary (or database row) per team,
                       each with at least "team_id" and "league_id"
    number_of_courts : how many games can be played at the same time
    allow_repetition : True if teams may meet more than once
    first_batch      : the number of the first batch to fill (normally 1;
                       higher when we re-plan the rest of a running tournament)
    earlier_games    : list of (team1_id, team2_id) pairs that are already in the
                       schedule and must be kept (used when teams are added later)

    Returns a list of dictionaries:
        {"batch": .., "court": .., "team1_id": .., "team2_id": .., "league_id": ..}
    """
    if earlier_games is None:
        earlier_games = []
    if number_of_courts < 1:
        number_of_courts = 1

    # --- Step 1: which team is in which league ---------------------------
    league_of = {}            # team_id -> league
    teams_per_league = {}     # league -> [team_id, team_id, ...]
    for team in teams:
        team_id = team["team_id"]
        league = team["league_id"]
        league_of[team_id] = league
        if league not in teams_per_league:
            teams_per_league[league] = []
        teams_per_league[league].append(team_id)

    # --- Step 2: count the games that already exist -------------------------
    times_met = {}              # (team_a, team_b) -> how often they play each other
    games_played = {}           # team_id -> number of games
    for team_id in league_of:
        games_played[team_id] = 0
    for (team_a, team_b) in earlier_games:
        key = pair_key(team_a, team_b)
        times_met[key] = times_met.get(key, 0) + 1
        if team_a in games_played:
            games_played[team_a] = games_played[team_a] + 1
        if team_b in games_played:
            games_played[team_b] = games_played[team_b] + 1

    # --- Step 3: list every game that still has to be played ---------------
    # progress tells how "far" in its league a game is (0.25 = first quarter).
    # Using a fraction keeps big and small leagues moving at the same speed.
    needed_games = []
    progress = {}
    for league in sorted(teams_per_league):
        rounds = round_robin_rounds(teams_per_league[league])
        for round_index in range(len(rounds)):
            for (team_a, team_b) in rounds[round_index]:
                key = pair_key(team_a, team_b)
                if times_met.get(key, 0) == 0:
                    needed_games.append(key)
                    progress[key] = (round_index + 1) / len(rounds)

    games_left = {}             # team_id -> number of needed games still to schedule
    for team_id in league_of:
        games_left[team_id] = 0
    for (team_a, team_b) in needed_games:
        games_left[team_a] = games_left[team_a] + 1
        games_left[team_b] = games_left[team_b] + 1

    # With repetition, nobody should end up with more games than the busiest
    # team would have anyway. This keeps repetition minimal.
    target_games = 0
    for team_id in league_of:
        total = games_played[team_id] + games_left[team_id]
        if total > target_games:
            target_games = total

    # When did each team play for the last time? (used for waiting time)
    last_batch_played = {}
    for team_id in league_of:
        last_batch_played[team_id] = first_batch - 1

    # --- Step 4: fill the batches one by one --------------------------------
    schedule = []
    batch = first_batch
    while len(needed_games) > 0:
        busy_teams = set()      # teams that already play in this batch
        chosen = []             # games chosen for this batch

        # Give every needed game a sort value: least progress first,
        # then the pair that has waited the longest (minus sign = biggest first)
        candidates = []
        for key in needed_games:
            team_a, team_b = key
            waiting = (batch - last_batch_played[team_a]) + (batch - last_batch_played[team_b])
            candidates.append((progress[key], -waiting, key))
        candidates.sort()

        for (game_progress, minus_waiting, key) in candidates:
            if len(chosen) == number_of_courts:
                break
            team_a, team_b = key
            if team_a in busy_teams or team_b in busy_teams:
                continue
            chosen.append(key)
            busy_teams.add(team_a)
            busy_teams.add(team_b)

        # Remove the chosen games from the "still needed" list
        for key in chosen:
            needed_games.remove(key)
            games_left[key[0]] = games_left[key[0]] - 1
            games_left[key[1]] = games_left[key[1]] - 1

        # Extra games on free courts (only if repetition is allowed)
        if allow_repetition:
            while len(chosen) < number_of_courts:
                extra = find_extra_game(teams_per_league, busy_teams, times_met,
                                        games_played, games_left, target_games,
                                        last_batch_played, batch)
                if extra is None:
                    break
                chosen.append(extra)
                busy_teams.add(extra[0])
                busy_teams.add(extra[1])

        # Write the chosen games into the schedule, court 1, 2, 3, ...
        court = 1
        for (team_a, team_b) in chosen:
            schedule.append({
                "batch": batch,
                "court": court,
                "team1_id": team_a,
                "team2_id": team_b,
                "league_id": league_of[team_a],
            })
            court = court + 1
            key = pair_key(team_a, team_b)
            times_met[key] = times_met.get(key, 0) + 1
            games_played[team_a] = games_played[team_a] + 1
            games_played[team_b] = games_played[team_b] + 1
            last_batch_played[team_a] = batch
            last_batch_played[team_b] = batch

        batch = batch + 1

    return schedule


def find_extra_game(teams_per_league, busy_teams, times_met, games_played,
                    games_left, target_games, last_batch_played, batch):
    """
    Find the best "repeat" game for a free court, or None if there is none.
    Best = the pair that met the least, then the teams with the fewest games,
    then the teams that waited longest.
    """
    best_game = None
    best_value = None
    for league in teams_per_league:
        team_ids = teams_per_league[league]
        for i in range(len(team_ids)):
            for j in range(i + 1, len(team_ids)):
                team_a = team_ids[i]
                team_b = team_ids[j]
                if team_a in busy_teams or team_b in busy_teams:
                    continue
                # Do not give a team more games than the busiest team will have
                if games_played[team_a] + games_left[team_a] >= target_games:
                    continue
                if games_played[team_b] + games_left[team_b] >= target_games:
                    continue
                key = pair_key(team_a, team_b)
                waiting = (batch - last_batch_played[team_a]) + (batch - last_batch_played[team_b])
                value = (times_met.get(key, 0), games_played[team_a] + games_played[team_b], -waiting, key)
                if best_value is None or value < best_value:
                    best_value = value
                    best_game = key
    return best_game


def count_batches(schedule):
    """How many batches does a schedule have?"""
    highest = 0
    for game in schedule:
        if game["batch"] > highest:
            highest = game["batch"]
    return highest


def estimate_number_of_batches(teams_per_league_count, number_of_courts, allow_repetition):
    """
    Before the tournament starts we want to show how long a game can take.
    For that we build a "fake" schedule with made-up teams and count the batches.

    teams_per_league_count : e.g. {1: 6, 2: 5, 3: 4}
    """
    fake_teams = []
    fake_id = 1
    for league in teams_per_league_count:
        for number in range(teams_per_league_count[league]):
            fake_teams.append({"team_id": fake_id, "league_id": league})
            fake_id = fake_id + 1
    schedule = build_schedule(fake_teams, number_of_courts, allow_repetition)
    return count_batches(schedule)


def find_batch_moves(game, all_games, current_batch, number_of_courts):
    """
    For the "Change batch" option: where can this game go?

    game        : the game the manager clicked on
    all_games   : every game of the tournament
    Only batches from the current batch up to the last one (+ one new batch at
    the end) are offered, never earlier ones.

    Returns a list of options. Every option is a dictionary:
        {"target_batch": t, "swap_game": None,  "court": c}   -> free court in batch t
        {"target_batch": t, "swap_game": other, "court": c}   -> swap with game 'other'
    """
    games_of_batch = {}     # batch -> list of games
    teams_of_batch = {}     # batch -> set of team ids playing in that batch
    last_batch = 0
    for other in all_games:
        batch = other["batch"]
        if batch not in games_of_batch:
            games_of_batch[batch] = []
            teams_of_batch[batch] = set()
        games_of_batch[batch].append(other)
        teams_of_batch[batch].add(other["team1_id"])
        teams_of_batch[batch].add(other["team2_id"])
        if batch > last_batch:
            last_batch = batch

    my_batch = game["batch"]
    my_teams = {game["team1_id"], game["team2_id"]}
    # Teams in my own batch, without my own game
    teams_left_in_my_batch = teams_of_batch.get(my_batch, set()) - my_teams

    options = []
    # last_batch + 1 = a brand new batch at the end of the schedule
    for target in range(current_batch, last_batch + 2):
        if target == my_batch:
            continue
        games_there = games_of_batch.get(target, [])
        teams_there = teams_of_batch.get(target, set())

        # Option A: there is a free court and neither of my teams plays there
        if len(games_there) < number_of_courts and len(my_teams & teams_there) == 0:
            used_courts = []
            for other in games_there:
                used_courts.append(other["court"])
            free_court = 1
            while free_court in used_courts:
                free_court = free_court + 1
            options.append({"target_batch": target, "swap_game": None, "court": free_court})

        # Option B: swap places with a game of that batch
        for other in games_there:
            if other["finished"]:
                continue
            other_teams = {other["team1_id"], other["team2_id"]}
            # My teams may not play in the target batch (apart from the game we swap out)
            if len(my_teams & (teams_there - other_teams)) > 0:
                continue
            # Their teams may not play in my batch (apart from my game)
            if len(other_teams & teams_left_in_my_batch) > 0:
                continue
            options.append({"target_batch": target, "swap_game": other, "court": other["court"]})

    return options
