"""
create_sample_tournament.py - fill the database with an example tournament.

Run it from this folder with:
    python create_sample_tournament.py

It creates (but does NOT start) a doubles tournament with:
    8 courts, 2 hours, no repetition
    Beginner league:      10 teams
    Intermediate league:  15 teams
    Advanced league:       7 teams
Running it twice creates the tournament twice.
"""

import database

TOURNAMENT_NAME = "BSC Leiden Sample Tournament"
TOURNAMENT_DATE = "2026-11-20"
NUMBER_OF_COURTS = 8
DURATION_MINUTES = 120

# league name -> list of team names (the leagues are created in this order)
TEAMS = {
    "Beginner": ["Shuttle Starters", "Net Rookies", "Leiden Lobbers", "Feather Friends", "Smash Sprouts",
        "Rapenburg Rackets", "First Serve", "Birdie Beginners", "Canal Clears", "Drop Shot Dreamers"],
    "Intermediate": ["Leiden Team CS", "Mid Court Mavericks", "Rally Rascals", "Drive Time", "Nieuwe Rijn Netters",
        "Backhand Bandits", "Clear Thinkers", "Hairpin Heroes", "Breestraat Birdies", "Flick Serve Five",
        "Sleutelstad Smashers", "Lift Off", "Push Shot Pals", "Burcht Badminton", "Tulip Twisters"],
    "Advanced": ["Jump Smash Kings", "BSC Elite", "Crosscourt Kings", "Net Kill Ninjas",
        "Pieterskerk Power", "Feather Storm", "Golden Shuttle"],
}

FIRST_NAMES = ["Anna", "Bram", "Chloe", "Daan", "Emma", "Finn", "Gijs", "Hanna", "Isa", "Jesse",
               "Julia", "Lars", "Lotte", "Milan", "Noor", "Olivier", "Puck", "Ruben", "Sara", "Thijs",
               "Vera", "Wout", "Yara", "Zoe", "Bas", "Eva", "Luuk", "Mila", "Sem", "Tess", "Jip", "Fleur"]
LAST_NAMES = ["de Vries", "Jansen", "Bakker", "Visser", "Smit", "Meijer", "de Boer", "Mulder",
              "de Groot", "Bos", "Vos", "Peters", "Hendriks", "van Dijk", "Dekker", "Brouwer"]


def make_player_name(number):
    """Make up a different player name for every number."""
    first = FIRST_NAMES[number % len(FIRST_NAMES)]
    last = LAST_NAMES[(number * 7) % len(LAST_NAMES)]
    return first + " " + last


def main():
    database.create_tables()
    connection = database.open_connection()

    number_of_players = 0
    for league_name in TEAMS:
        number_of_players = number_of_players + 2 * len(TEAMS[league_name])

    cursor = connection.execute(
        "INSERT INTO tournaments (name, date, game_type, num_courts, expected_people, "
        "expected_minutes, allow_repetition) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (TOURNAMENT_NAME, TOURNAMENT_DATE, "doubles", NUMBER_OF_COURTS,
         number_of_players, DURATION_MINUTES, 0),
    )
    tournament_id = cursor.lastrowid

    player_number = 0
    position = 1
    for league_name in TEAMS:
        cursor = connection.execute(
            "INSERT INTO leagues (tournament_id, name, position) VALUES (?, ?, ?)",
            (tournament_id, league_name, position),
        )
        league_id = cursor.lastrowid
        position = position + 1
        for team_name in TEAMS[league_name]:
            member1 = make_player_name(player_number)
            member2 = make_player_name(player_number + 1)
            player_number = player_number + 2
            connection.execute(
                "INSERT INTO teams (tournament_id, team_name, member1, member2, league_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (tournament_id, team_name, member1, member2, league_id),
            )

    connection.commit()
    connection.close()
    print("Created '" + TOURNAMENT_NAME + "' (tournament_id " + str(tournament_id) + ") with "
          + str(player_number // 2) + " teams. It has not been started.")


if __name__ == "__main__":
    main()
