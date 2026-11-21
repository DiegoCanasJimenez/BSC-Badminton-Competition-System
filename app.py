"""
app.py - the website itself (all pages and buttons).

Run it locally with:
    python app.py
and open http://127.0.0.1:5000 in your browser.

Structure of the project:
    app.py        - pages / buttons (this file)
    database.py   - the tables and the database connection
    scheduler.py  - builds the concept schedule and the "change batch" options
    ranking.py    - points per game and the ranking table
    timing.py     - game length and estimated start times
    templates/    - the HTML pages
    static/       - style sheet, JavaScript and the BSC logo
"""

import os

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import database
import timing
from database import get_db
from ranking import build_ranking
from scheduler import build_schedule, count_batches, estimate_number_of_batches, find_batch_moves

app = Flask(__name__)

# The secret key protects the login cookie. On a real server ALWAYS set the
# SECRET_KEY environment variable to a long random text (see README.md).
app.secret_key = os.environ.get("SECRET_KEY", "local-development-key-change-me")
# Browsers will not send the login cookie along with forms from other websites
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Close the database connection after every request
app.teardown_appcontext(database.close_db)

ORGANIZER = "BSC Leiden"
# Every tournament has its own leagues (table 'leagues'). A new tournament
# starts with these; managers can add, rename or remove leagues in the form.
DEFAULT_LEAGUES = ["Beginner", "Intermediate", "Advanced"]
# Team names longer than this are cut off on the courts (the rest becomes "…")
MAX_NAME_LENGTH_ON_COURT = 22


# ===========================================================================
# Start-up
# ===========================================================================

def setup():
    """Create the tables and, the very first time, a manager account 'admin'."""
    database.create_tables()
    connection = database.open_connection()
    number_of_managers = connection.execute("SELECT COUNT(*) FROM managers").fetchone()[0]
    if number_of_managers == 0:
        password = os.environ.get("ADMIN_PASSWORD", "admin")
        connection.execute(
            "INSERT INTO managers (username, password_hash) VALUES (?, ?)",
            ("admin", generate_password_hash(password)),
        )
        connection.commit()
        print("Created manager account 'admin'. Change the password with: python create_manager.py")
    connection.close()


setup()


# ===========================================================================
# Small helpers
# ===========================================================================

def is_manager():
    """True if the visitor is logged in as a manager."""
    return "manager" in session


def short_name(name):
    """Cut long team names so they always fit on a court."""
    if len(name) > MAX_NAME_LENGTH_ON_COURT:
        return name[:MAX_NAME_LENGTH_ON_COURT - 1] + "…"
    return name


def read_whole_number(text, minimum):
    """Turn form text into a whole number. Gives None if it is not valid."""
    try:
        number = int(str(text).strip())
    except ValueError:
        return None
    if number < minimum:
        return None
    return number


def safe_next_page(page):
    """Only allow redirects to pages of our own website."""
    if page and page.startswith("/") and not page.startswith("//"):
        return page
    return url_for("index")


def go_back(default_page):
    """
    After a manager action: go back to the page the form came from (the form
    sends it in a hidden field called 'next', e.g. the team history page),
    otherwise to default_page (normally the dashboard).
    """
    next_page = request.form.get("next", "")
    if next_page.startswith("/") and not next_page.startswith("//"):
        return redirect(next_page)
    return redirect(default_page)


def read_clock_time(text):
    """'14:35' -> (14, 35). Gives None if it is not a valid time."""
    parts = str(text).strip().split(":")
    if len(parts) != 2:
        return None
    hours = read_whole_number(parts[0], 0)
    minutes = read_whole_number(parts[1], 0)
    if hours is None or minutes is None or hours > 23 or minutes > 59:
        return None
    return (hours, minutes)


def time_on_tournament_day(tournament, hours, minutes):
    """Combine a clock time with the day the tournament was started."""
    day = tournament["started_at"][:10] if tournament["started_at"] else tournament["date"]
    return day + " " + str(hours).zfill(2) + ":" + str(minutes).zfill(2)


def remove_team_warning(team_name, started, finished_games=0):
    """The question shown before a team is removed."""
    text = "Remove '" + team_name + "'?"
    if started:
        text = text + " Its games are taken out of the schedule and the rest of the schedule is planned again."
        if finished_games:
            text = text + " Its " + str(finished_games) + " finished game(s) will no longer count for the ranking."
        text = text + " This cannot be undone."
    return text


def duration_text(minutes):
    """150 -> '2h30'."""
    return str(minutes // 60) + "h" + str(minutes % 60).zfill(2)


# These names can be used inside every HTML template
@app.context_processor
def add_helpers_to_templates():
    return {
        "is_manager": is_manager(),
        "organizer": ORGANIZER,
        "clock": timing.clock,
        "short_name": short_name,
        "remove_team_warning": remove_team_warning,
        "duration_text": duration_text,
    }


# ===========================================================================
# Loading data from the database
# ===========================================================================

def load_tournament(tournament_id):
    tournament = get_db().execute(
        "SELECT * FROM tournaments WHERE tournament_id = ?", (tournament_id,)
    ).fetchone()
    if tournament is None:
        abort(404)
    return tournament


def load_teams(tournament_id):
    return get_db().execute(
        "SELECT * FROM teams WHERE tournament_id = ? ORDER BY team_name COLLATE NOCASE",
        (tournament_id,),
    ).fetchall()


def load_team(team_id):
    team = get_db().execute("SELECT * FROM teams WHERE team_id = ?", (team_id,)).fetchone()
    if team is None:
        abort(404)
    return team


def count_team_games(team_id):
    """(number of finished games, number of games not played yet) of one team."""
    row = get_db().execute(
        "SELECT COALESCE(SUM(finished), 0) AS finished, COUNT(*) AS total FROM games "
        "WHERE team1_id = ? OR team2_id = ?",
        (team_id, team_id),
    ).fetchone()
    return row["finished"], row["total"] - row["finished"]


def load_leagues(tournament_id):
    """The leagues of a tournament, in the order chosen by the manager."""
    return get_db().execute(
        "SELECT * FROM leagues WHERE tournament_id = ? ORDER BY position, league_id",
        (tournament_id,),
    ).fetchall()


def make_league_name_list(leagues):
    """Dictionary league_id -> league name."""
    names = {}
    for league in leagues:
        names[league["league_id"]] = league["name"]
    return names


def load_games(tournament_id):
    return get_db().execute(
        "SELECT * FROM games WHERE tournament_id = ? ORDER BY batch, court",
        (tournament_id,),
    ).fetchall()


def load_game(game_id):
    game = get_db().execute("SELECT * FROM games WHERE game_id = ?", (game_id,)).fetchone()
    if game is None:
        abort(404)
    return game


def make_team_name_list(teams):
    """Dictionary team_id -> team name."""
    names = {}
    for team in teams:
        names[team["team_id"]] = team["team_name"]
    return names


def count_players(teams):
    """Number of people that registered (1 per singles team, 2 per doubles team)."""
    players = 0
    for team in teams:
        players = players + 1
        if team["member2"]:
            players = players + 1
    return players


def expected_end_text(last_batch_start, game_minutes):
    """When the last game is expected to end, or None if there is no schedule."""
    if not last_batch_start or not game_minutes:
        return None
    return timing.add_minutes(last_batch_start, game_minutes)


def batch_start_texts(games):
    """Dictionary batch -> estimated start time text (from the games table)."""
    starts = {}
    for game in games:
        if game["batch"] not in starts:
            starts[game["batch"]] = game["estimated_start"]
    return starts


def insert_games(tournament_id, schedule):
    """Save a list of planned games into the games table."""
    db = get_db()
    for game in schedule:
        db.execute(
            "INSERT INTO games (tournament_id, batch, court, team1_id, team2_id, league_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tournament_id, game["batch"], game["court"], game["team1_id"],
             game["team2_id"], game["league_id"]),
        )


# ===========================================================================
# Keeping the schedule up to date
# ===========================================================================

def refresh_estimated_times(tournament_id):
    """
    Calculate the estimated start time of every batch again and save it in
    the games table. Called after START, "Update time", moving a game, ...
    """
    db = get_db()
    tournament = load_tournament(tournament_id)
    if tournament["status"] != "started":
        return
    games = load_games(tournament_id)
    number_of_batches = count_batches(games)

    real_start_times = {}
    rows = db.execute(
        "SELECT batch, actual_start FROM batch_times WHERE tournament_id = ?", (tournament_id,)
    ).fetchall()
    for row in rows:
        real_start_times[row["batch"]] = timing.text_to_time(row["actual_start"])

    times = timing.calculate_batch_start_times(
        timing.text_to_time(tournament["started_at"]),
        tournament["game_minutes"],
        number_of_batches,
        real_start_times,
    )
    for batch in times:
        db.execute(
            "UPDATE games SET estimated_start = ? WHERE tournament_id = ? AND batch = ?",
            (timing.time_to_text(times[batch]), tournament_id, batch),
        )
    db.commit()


def remove_empty_batches(tournament_id):
    """
    After moving games a batch can become empty. We renumber the batches so
    there are no holes (1, 2, 4 becomes 1, 2, 3).
    Returns a dictionary old batch number -> new batch number.
    """
    db = get_db()
    rows = db.execute(
        "SELECT DISTINCT batch FROM games WHERE tournament_id = ? ORDER BY batch", (tournament_id,)
    ).fetchall()
    batches_in_use = []
    for row in rows:
        batches_in_use.append(row["batch"])

    # Real start times of batches that no longer exist are thrown away
    for row in db.execute(
        "SELECT batch FROM batch_times WHERE tournament_id = ?", (tournament_id,)
    ).fetchall():
        if row["batch"] not in batches_in_use:
            db.execute("DELETE FROM batch_times WHERE tournament_id = ? AND batch = ?",
                       (tournament_id, row["batch"]))

    new_numbers = {}
    new_number = 1
    for old_number in batches_in_use:
        new_numbers[old_number] = new_number
        if old_number != new_number:
            db.execute("UPDATE games SET batch = ? WHERE tournament_id = ? AND batch = ?",
                       (new_number, tournament_id, old_number))
            db.execute("UPDATE batch_times SET batch = ? WHERE tournament_id = ? AND batch = ?",
                       (new_number, tournament_id, old_number))
        new_number = new_number + 1

    tournament = load_tournament(tournament_id)
    current = tournament["current_batch"]
    if current in new_numbers:
        current = new_numbers[current]
    elif len(batches_in_use) > 0 and current > len(batches_in_use):
        current = len(batches_in_use)
    db.execute("UPDATE tournaments SET current_batch = ? WHERE tournament_id = ?", (current, tournament_id))
    db.commit()
    return new_numbers


def rebuild_remaining_schedule(tournament):
    """
    DYNAMIC TOURNAMENT: teams were added, removed or moved to another league
    after the tournament started.

    We keep every game that is finished or that is in a batch up to the current
    batch (those are being played right now). All later games that were not
    played yet are thrown away and planned again with the teams as they are now.
    Results are never lost: finished games are never deleted, and the ranking
    is always calculated from the finished games (see ranking.py).
    """
    db = get_db()
    tournament_id = tournament["tournament_id"]
    current_batch = tournament["current_batch"]

    db.execute(
        "DELETE FROM games WHERE tournament_id = ? AND finished = 0 AND batch > ?",
        (tournament_id, current_batch),
    )
    kept_games = load_games(tournament_id)
    earlier_pairs = []
    for game in kept_games:
        earlier_pairs.append((game["team1_id"], game["team2_id"]))

    first_new_batch = max(count_batches(kept_games), current_batch) + 1
    new_games = build_schedule(
        load_teams(tournament_id),
        tournament["num_courts"],
        tournament["allow_repetition"] == 1,
        first_new_batch,
        earlier_pairs,
    )
    insert_games(tournament_id, new_games)
    db.commit()
    remove_empty_batches(tournament_id)
    refresh_estimated_times(tournament_id)


# ===========================================================================
# Pages: home, login, logout
# ===========================================================================

@app.route("/")
def index():
    tournaments = get_db().execute("""
        SELECT tournaments.*,
            (SELECT COUNT(*) FROM teams WHERE teams.tournament_id = tournaments.tournament_id) AS team_count,
            (SELECT COUNT(*) FROM games WHERE games.tournament_id = tournaments.tournament_id) AS game_count,
            (SELECT COUNT(*) FROM games WHERE games.tournament_id = tournaments.tournament_id
                                         AND games.finished = 1) AS finished_count,
            (SELECT MAX(estimated_start) FROM games
                WHERE games.tournament_id = tournaments.tournament_id) AS last_batch_start
        FROM tournaments
        ORDER BY date DESC, tournament_id DESC
    """).fetchall()
    cards = []
    for row in tournaments:
        card = dict(row)
        card["expected_end"] = expected_end_text(row["last_batch_start"], row["game_minutes"])
        cards.append(card)
    return render_template("index.html", tournaments=cards)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        manager = get_db().execute(
            "SELECT * FROM managers WHERE username = ?", (username,)
        ).fetchone()
        if manager is not None and check_password_hash(manager["password_hash"], password):
            session.clear()
            session["manager"] = manager["username"]
            flash("Welcome, " + manager["username"] + "! You can now add and change tournaments.", "success")
            return redirect(safe_next_page(request.args.get("next")))
        flash("Wrong username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You are logged out.", "success")
    return redirect(url_for("index"))


# ===========================================================================
# Pages: create / edit / delete a tournament
# ===========================================================================

def read_tournament_form(form):
    """Read and check the tournament form. Returns (values, list of errors)."""
    errors = []
    values = {
        "name": form.get("name", "").strip(),
        "date": form.get("date", "").strip(),
        "game_type": form.get("game_type", "singles"),
        "num_courts": read_whole_number(form.get("num_courts", ""), 1),
        "expected_people": read_whole_number(form.get("expected_people", ""), 0),
        "duration_hours": read_whole_number(form.get("duration_hours", "0") or "0", 0),
        "duration_minutes": read_whole_number(form.get("duration_minutes", "0") or "0", 0),
        "allow_repetition": 1 if form.get("allow_repetition") == "yes" else 0,
    }
    if values["name"] == "":
        errors.append("Please fill in a name.")
    if values["date"] == "":
        errors.append("Please choose a date.")
    if values["game_type"] not in ("singles", "doubles"):
        errors.append("Choose singles or doubles.")
    if values["num_courts"] is None:
        errors.append("The number of courts must be 1 or more.")
    if values["expected_people"] is None:
        errors.append("The expected number of people must be 0 or more.")
    if values["duration_hours"] is None or values["duration_minutes"] is None:
        errors.append("The duration must be whole hours and minutes.")
    else:
        values["expected_minutes"] = values["duration_hours"] * 60 + values["duration_minutes"]
        if values["expected_minutes"] < 10:
            errors.append("The tournament should last at least 10 minutes.")
    return values, errors


def read_league_form(form):
    """
    Read the league rows of the tournament form.
    Every row sends a 'league_id' (empty for a new league) and a 'league_name'.
    Returns (rows, errors); rows are in the order of the form.
    """
    league_ids = form.getlist("league_id")
    league_names = form.getlist("league_name")
    rows = []
    errors = []
    names_seen = []
    for i in range(len(league_names)):
        name = league_names[i].strip()
        league_id = None
        if i < len(league_ids):
            league_id = read_whole_number(league_ids[i], 1)
        if name == "":
            if league_id is None:
                continue  # an empty new row is simply ignored
            errors.append("Every league needs a name.")
            continue
        if name.lower() in names_seen:
            errors.append("There are two leagues called '" + name + "'.")
        names_seen.append(name.lower())
        rows.append({"league_id": league_id, "name": name, "team_count": 0})
    if len(rows) == 0:
        errors.append("Add at least one league.")
    return rows, errors


def save_leagues(tournament_id, rows):
    """
    Make the leagues of a tournament the same as 'rows' (from read_league_form):
    new rows are added, existing ones renamed and put in the new order, and
    leagues that are no longer in the form are deleted.
    A league that still has teams is never deleted: then a list of errors is
    returned and nothing is changed.
    """
    db = get_db()
    kept_ids = []
    for row in rows:
        if row["league_id"] is not None:
            kept_ids.append(row["league_id"])

    errors = []
    removed_ids = []
    for league in load_leagues(tournament_id):
        if league["league_id"] in kept_ids:
            continue
        number_of_teams = db.execute(
            "SELECT COUNT(*) FROM teams WHERE league_id = ?", (league["league_id"],)
        ).fetchone()[0]
        if number_of_teams > 0:
            errors.append("The league '" + league["name"] + "' still has " + str(number_of_teams)
                          + " team(s), so it cannot be removed.")
        removed_ids.append(league["league_id"])
    if errors:
        return errors

    for league_id in removed_ids:
        db.execute("DELETE FROM leagues WHERE league_id = ?", (league_id,))
    position = 1
    for row in rows:
        if row["league_id"] is None:
            db.execute("INSERT INTO leagues (tournament_id, name, position) VALUES (?, ?, ?)",
                       (tournament_id, row["name"], position))
        else:
            db.execute("UPDATE leagues SET name = ?, position = ? WHERE league_id = ? AND tournament_id = ?",
                       (row["name"], position, row["league_id"], tournament_id))
        position = position + 1
    return []


def leagues_with_team_counts(tournament_id):
    """The leagues as form rows, with how many teams each one has."""
    rows = []
    for league in load_leagues(tournament_id):
        number_of_teams = get_db().execute(
            "SELECT COUNT(*) FROM teams WHERE league_id = ?", (league["league_id"],)
        ).fetchone()[0]
        rows.append({"league_id": league["league_id"], "name": league["name"], "team_count": number_of_teams})
    return rows


@app.route("/tournament/new", methods=["GET", "POST"])
def new_tournament():
    if not is_manager():
        return redirect(url_for("login", next=request.path))

    if request.method == "POST":
        values, errors = read_tournament_form(request.form)
        league_rows, league_errors = read_league_form(request.form)
        errors = errors + league_errors
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("tournament_form.html", values=values, leagues=league_rows,
                                   editing=False, locked=False)

        db = get_db()
        cursor = db.execute(
            "INSERT INTO tournaments (name, date, game_type, num_courts, expected_people, "
            "expected_minutes, allow_repetition) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (values["name"], values["date"], values["game_type"], values["num_courts"],
             values["expected_people"], values["expected_minutes"], values["allow_repetition"]),
        )
        save_leagues(cursor.lastrowid, league_rows)
        db.commit()
        flash("Tournament created. Now add the teams!", "success")
        return redirect(url_for("dashboard", tournament_id=cursor.lastrowid))

    empty_values = {"name": "", "date": "", "game_type": "singles", "num_courts": 4,
                    "expected_people": 24, "duration_hours": 3, "duration_minutes": 0,
                    "allow_repetition": 0}
    default_leagues = []
    for name in DEFAULT_LEAGUES:
        default_leagues.append({"league_id": None, "name": name, "team_count": 0})
    return render_template("tournament_form.html", values=empty_values, leagues=default_leagues,
                           editing=False, locked=False)


@app.route("/tournament/<int:tournament_id>/edit", methods=["GET", "POST"])
def edit_tournament(tournament_id):
    if not is_manager():
        return redirect(url_for("login", next=request.path))
    tournament = load_tournament(tournament_id)
    # Once the schedule exists, only the name and the date can still change
    locked = tournament["status"] == "started"

    if request.method == "POST":
        values, errors = read_tournament_form(request.form)
        if locked:
            # Greyed-out fields are not sent by the browser, so only check name and date
            errors = []
            if values["name"] == "":
                errors.append("Please fill in a name.")
            if values["date"] == "":
                errors.append("Please choose a date.")
        # Leagues can always be changed (also after the start).
        # (If the form has no league fields at all, the leagues stay as they are.)
        if "league_name" in request.form:
            league_rows, league_errors = read_league_form(request.form)
            errors = errors + league_errors
            if not errors:
                errors = save_leagues(tournament_id, league_rows)
        if errors:
            # Nothing is saved (also not the leagues): show the form again with what was typed
            get_db().rollback()
            for error in errors:
                flash(error, "error")
            if locked:
                values = dict(tournament, name=values["name"], date=values["date"])
                values["duration_hours"] = tournament["expected_minutes"] // 60
                values["duration_minutes"] = tournament["expected_minutes"] % 60
            if "league_name" in request.form:
                league_rows = read_league_form(request.form)[0]
                counts = {}
                for row in leagues_with_team_counts(tournament_id):
                    counts[row["league_id"]] = row["team_count"]
                for row in league_rows:
                    row["team_count"] = counts.get(row["league_id"], 0)
            else:
                league_rows = leagues_with_team_counts(tournament_id)
            return render_template("tournament_form.html", values=values, editing=True,
                                   leagues=league_rows, locked=locked, tournament=tournament)

        db = get_db()
        if locked:
            db.execute("UPDATE tournaments SET name = ?, date = ? WHERE tournament_id = ?",
                       (values["name"], values["date"], tournament_id))
        else:
            db.execute(
                "UPDATE tournaments SET name = ?, date = ?, game_type = ?, num_courts = ?, "
                "expected_people = ?, expected_minutes = ?, allow_repetition = ? WHERE tournament_id = ?",
                (values["name"], values["date"], values["game_type"], values["num_courts"],
                 values["expected_people"], values["expected_minutes"], values["allow_repetition"],
                 tournament_id),
            )
        db.commit()
        flash("Tournament updated.", "success")
        return redirect(url_for("dashboard", tournament_id=tournament_id))

    values = dict(tournament)
    values["duration_hours"] = tournament["expected_minutes"] // 60
    values["duration_minutes"] = tournament["expected_minutes"] % 60
    return render_template("tournament_form.html", values=values, editing=True,
                           leagues=leagues_with_team_counts(tournament_id),
                           locked=locked, tournament=tournament)


@app.route("/tournament/<int:tournament_id>/delete", methods=["POST"])
def delete_tournament(tournament_id):
    if not is_manager():
        abort(403)
    load_tournament(tournament_id)
    db = get_db()
    db.execute("DELETE FROM games WHERE tournament_id = ?", (tournament_id,))
    db.execute("DELETE FROM batch_times WHERE tournament_id = ?", (tournament_id,))
    db.execute("DELETE FROM teams WHERE tournament_id = ?", (tournament_id,))
    db.execute("DELETE FROM leagues WHERE tournament_id = ?", (tournament_id,))
    db.execute("DELETE FROM tournaments WHERE tournament_id = ?", (tournament_id,))
    db.commit()
    flash("Tournament deleted.", "success")
    return redirect(url_for("index"))


# ===========================================================================
# Page: the dashboard of one tournament
# ===========================================================================

def expected_teams_per_league(tournament, leagues):
    """
    Before teams are added we guess the number of teams from the expected
    number of people, spread evenly over the leagues.
    """
    if tournament["game_type"] == "doubles":
        number_of_teams = tournament["expected_people"] // 2
    else:
        number_of_teams = tournament["expected_people"]
    counts = {}
    if len(leagues) == 0:
        return counts
    for league in leagues:
        counts[league["league_id"]] = number_of_teams // len(leagues)
    # Spread what is left over (e.g. 10 teams over 3 leagues -> 4, 3, 3)
    for i in range(number_of_teams % len(leagues)):
        league_id = leagues[i]["league_id"]
        counts[league_id] = counts[league_id] + 1
    return counts


@app.route("/tournament/<int:tournament_id>")
def dashboard(tournament_id):
    tournament = load_tournament(tournament_id)
    leagues = load_leagues(tournament_id)
    teams = load_teams(tournament_id)
    games = load_games(tournament_id)
    names = make_team_name_list(teams)
    ranking = build_ranking(teams, games)
    started = tournament["status"] == "started"

    # How many teams are in each league?
    teams_per_league = {}
    for league in leagues:
        teams_per_league[league["league_id"]] = 0
    for team in teams:
        teams_per_league[team["league_id"]] = teams_per_league.get(team["league_id"], 0) + 1

    # --- How long can one game take? ---------------------------------------
    if started:
        number_of_batches = count_batches(games)
        game_minutes = tournament["game_minutes"]
        estimate_basis = "the schedule"
    else:
        if len(teams) > 0:
            counts = teams_per_league
            estimate_basis = str(len(teams)) + " registered teams"
        else:
            counts = expected_teams_per_league(tournament, leagues)
            estimate_basis = str(tournament["expected_people"]) + " expected people"
        number_of_batches = estimate_number_of_batches(
            counts, tournament["num_courts"], tournament["allow_repetition"] == 1)
        game_minutes = timing.calculate_game_minutes(tournament["expected_minutes"], number_of_batches)

    # --- Times of every batch and the expected end ----------------------------
    start_texts = batch_start_texts(games)
    estimated_end = None        # when the last game should end
    end_is_guess = False        # True before START: "if we started right now"
    minutes_late = None         # expected end compared with the planned duration
    if started:
        estimated_end = expected_end_text(start_texts.get(number_of_batches), game_minutes)
        if estimated_end and tournament["started_at"]:
            planned_end = timing.add_minutes(tournament["started_at"], tournament["expected_minutes"])
            minutes_late = timing.minutes_between(planned_end, estimated_end)
    elif tournament["date"] == timing.now_text()[:10] and number_of_batches > 0:
        estimated_end = timing.add_minutes(timing.now_text(),
                                           timing.schedule_minutes(game_minutes, number_of_batches))
        end_is_guess = True

    # --- One panel per league: ranking, current games and upcoming games ------
    # Batches before the current batch are not shown in the games list.
    current_batch = tournament["current_batch"]
    current_start = start_texts.get(current_batch)
    panels = []
    for league in leagues:
        league_id = league["league_id"]
        current_games = []     # this league's games in the current batch
        upcoming = []          # list of (batch, start text, [games]) for every later batch
        for game in games:
            if game["league_id"] != league_id:
                continue
            if game["batch"] == current_batch:
                current_games.append(game)
            elif game["batch"] > current_batch:
                if len(upcoming) == 0 or upcoming[-1][0] != game["batch"]:
                    upcoming.append((game["batch"], game["estimated_start"], []))
                upcoming[-1][2].append(game)
        panels.append({
            "league": league,
            "team_count": teams_per_league.get(league_id, 0),
            "ranking": ranking.get(league_id, []),
            "current_games": current_games,
            "upcoming": upcoming,
        })

    finished_games = 0
    for game in games:
        if game["finished"]:
            finished_games = finished_games + 1

    # Finished games per team (shown in the "Remove team?" question)
    played = {}
    for lines in ranking.values():
        for line in lines:
            played[line["team_id"]] = line["played"]

    open_batch = read_whole_number(request.args.get("batch", ""), 1)

    return render_template(
        "dashboard.html",
        tournament=tournament,
        teams=teams,
        names=names,
        leagues=leagues,
        league_names=make_league_name_list(leagues),
        panels=panels,
        started=started,
        players=count_players(teams),
        number_of_batches=number_of_batches,
        game_minutes=game_minutes,
        pause_minutes=timing.PAUSE_MINUTES,
        estimate_basis=estimate_basis,
        start_texts=start_texts,
        estimated_end=estimated_end,
        end_is_guess=end_is_guess,
        minutes_late=minutes_late,
        current_start=current_start,
        total_games=len(games),
        finished_games=finished_games,
        played=played,
        open_batch=open_batch,
    )


# ===========================================================================
# Teams
# ===========================================================================

def check_team_row(row, doubles, league_ids, taken_names):
    """
    Check one team (from the add-teams or the edit-team form).
    taken_names = the names (in lower case) that other teams already use.
    Returns a list of problems, empty if everything is fine.
    """
    errors = []
    if row["team_name"] == "":
        errors.append("the team name is missing.")
    elif row["team_name"].lower() in taken_names:
        errors.append("there is already a team called '" + row["team_name"] + "'.")
    if row["member1"] == "":
        errors.append("member 1 is missing." if doubles else "the player is missing.")
    if doubles and row["member2"] == "":
        errors.append("member 2 is missing (this is a doubles tournament).")
    if row["league_id"] not in league_ids:
        errors.append("choose a league.")
    for field in ("team_name", "member1", "member2"):
        if len(row[field]) > 60:
            errors.append("names can be at most 60 characters long.")
            break
    return errors


@app.route("/tournament/<int:tournament_id>/teams/add", methods=["GET", "POST"])
def add_teams(tournament_id):
    if not is_manager():
        return redirect(url_for("login", next=request.path))
    tournament = load_tournament(tournament_id)
    doubles = tournament["game_type"] == "doubles"
    leagues = load_leagues(tournament_id)
    league_ids = []
    for league in leagues:
        league_ids.append(league["league_id"])
    if len(leagues) == 0:
        flash("This tournament has no leagues yet. Add one with 'Edit tournament' first.", "error")
        return redirect(url_for("dashboard", tournament_id=tournament_id))

    if request.method == "POST":
        # Every row of the form sends one value of each list
        team_names = request.form.getlist("team_name")
        members1 = request.form.getlist("member1")
        members2 = request.form.getlist("member2")
        chosen_leagues = request.form.getlist("league_id")

        existing_names = []
        for team in load_teams(tournament_id):
            existing_names.append(team["team_name"].lower())

        rows = []
        errors = []
        for i in range(len(team_names)):
            row = {
                "team_name": team_names[i].strip(),
                "member1": members1[i].strip() if i < len(members1) else "",
                "member2": members2[i].strip() if i < len(members2) else "",
                "league_id": read_whole_number(chosen_leagues[i] if i < len(chosen_leagues) else "", 1),
            }
            # Completely empty rows are skipped
            if row["team_name"] == "" and row["member1"] == "" and row["member2"] == "":
                continue
            rows.append(row)
            for error in check_team_row(row, doubles, league_ids, existing_names):
                errors.append("Row " + str(i + 1) + ": " + error)
            existing_names.append(row["team_name"].lower())

        if len(rows) == 0:
            errors.append("Fill in at least one team.")
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("add_teams.html", tournament=tournament, rows=rows,
                                   doubles=doubles, leagues=leagues)

        db = get_db()
        for row in rows:
            member2 = row["member2"] if doubles else None
            db.execute(
                "INSERT INTO teams (tournament_id, team_name, member1, member2, league_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (tournament_id, row["team_name"], row["member1"], member2, row["league_id"]),
            )
        # The expected number of people grows when more people registered
        players = count_players(load_teams(tournament_id))
        if players > tournament["expected_people"]:
            db.execute("UPDATE tournaments SET expected_people = ? WHERE tournament_id = ?",
                       (players, tournament_id))
        db.commit()

        if tournament["status"] == "started":
            rebuild_remaining_schedule(load_tournament(tournament_id))
            flash(str(len(rows)) + " team(s) added. The games that were not played yet "
                  "have been planned again, results so far are kept.", "success")
        else:
            flash(str(len(rows)) + " team(s) added.", "success")
        return redirect(url_for("dashboard", tournament_id=tournament_id))

    empty_row = {"team_name": "", "member1": "", "member2": "", "league_id": league_ids[0]}
    return render_template("add_teams.html", tournament=tournament, rows=[empty_row],
                           doubles=doubles, leagues=leagues)


@app.route("/team/<int:team_id>/edit", methods=["GET", "POST"])
def edit_team(team_id):
    """
    Change a team: its name, its members and its league.

    The other tables (games, ranking, schedule) only store the team_id, never
    the name, so a new name or member is shown everywhere straight away.

    Changing the league after the start is only possible while the team has
    not finished a game yet: its planned games are thrown away and the rest
    of the schedule is planned again (the same as when a team is added).
    """
    if not is_manager():
        return redirect(url_for("login", next=request.path))
    team = load_team(team_id)
    tournament_id = team["tournament_id"]
    tournament = load_tournament(tournament_id)
    started = tournament["status"] == "started"
    doubles = tournament["game_type"] == "doubles"
    leagues = load_leagues(tournament_id)
    league_ids = [league["league_id"] for league in leagues]
    finished_games, planned_games = count_team_games(team_id)
    default_page = url_for("team_history", team_id=team_id)

    if request.method == "POST":
        row = {
            "team_name": request.form.get("team_name", "").strip(),
            "member1": request.form.get("member1", "").strip(),
            "member2": request.form.get("member2", "").strip() if doubles else "",
            "league_id": read_whole_number(request.form.get("league_id", ""), 1),
        }
        taken_names = []
        for other in load_teams(tournament_id):
            if other["team_id"] != team_id:
                taken_names.append(other["team_name"].lower())
        errors = []
        for error in check_team_row(row, doubles, league_ids, taken_names):
            errors.append(error[0].upper() + error[1:])
        league_changed = row["league_id"] != team["league_id"]
        if started and league_changed and finished_games > 0:
            errors.append("This team already finished " + str(finished_games) + " game(s) in its league, "
                          "so it cannot change league any more. You can remove it and add it again instead.")
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("edit_team.html", team=team, row=row, tournament=tournament,
                                   leagues=leagues, doubles=doubles, started=started,
                                   finished_games=finished_games, planned_games=planned_games,
                                   next_page=request.form.get("next", ""))

        db = get_db()
        db.execute(
            "UPDATE teams SET team_name = ?, member1 = ?, member2 = ?, league_id = ? WHERE team_id = ?",
            (row["team_name"], row["member1"], row["member2"] if doubles else None,
             row["league_id"], team_id),
        )
        if started and league_changed:
            # Its games were against teams of the old league: plan them again
            db.execute("DELETE FROM games WHERE finished = 0 AND (team1_id = ? OR team2_id = ?)",
                       (team_id, team_id))
            db.commit()
            rebuild_remaining_schedule(load_tournament(tournament_id))
            flash("Team updated and moved to another league. The games that were not played yet "
                  "have been planned again.", "success")
        else:
            db.commit()
            flash("Team updated. The new names are shown everywhere (schedule, ranking and courts).", "success")
        return go_back(default_page)

    row = {"team_name": team["team_name"], "member1": team["member1"],
           "member2": team["member2"] or "", "league_id": team["league_id"]}
    next_page = request.args.get("next", "")
    return render_template("edit_team.html", team=team, row=row, tournament=tournament,
                           leagues=leagues, doubles=doubles, started=started,
                           finished_games=finished_games, planned_games=planned_games,
                           next_page=next_page if safe_next_page(next_page) == next_page else "")


@app.route("/team/<int:team_id>/delete", methods=["POST"])
def delete_team(team_id):
    """
    Remove a team, also while the tournament is running (e.g. somebody went home).

    All games of the team are deleted:
      * games that were not played yet can never be played any more;
      * finished games against this team no longer count, so every team of the
        league is treated the same (the ranking is calculated from the games).
    After the start, the rest of the schedule is planned again without the team.
    """
    if not is_manager():
        abort(403)
    team = load_team(team_id)
    tournament_id = team["tournament_id"]
    tournament = load_tournament(tournament_id)
    finished_games, planned_games = count_team_games(team_id)

    db = get_db()
    db.execute("DELETE FROM games WHERE team1_id = ? OR team2_id = ?", (team_id, team_id))
    db.execute("DELETE FROM teams WHERE team_id = ?", (team_id,))
    db.commit()

    message = "Team '" + team["team_name"] + "' removed."
    if tournament["status"] == "started":
        rebuild_remaining_schedule(load_tournament(tournament_id))
        message = message + " The schedule has been planned again without this team."
        if finished_games > 0:
            message = (message + " Its " + str(finished_games) + " finished game(s) no longer count "
                       "for the ranking.")
    flash(message, "success")
    return redirect(url_for("dashboard", tournament_id=tournament_id))


# ===========================================================================
# START the tournament: build the concept schedule
# ===========================================================================

@app.route("/tournament/<int:tournament_id>/start", methods=["POST"])
def start_tournament(tournament_id):
    if not is_manager():
        abort(403)
    tournament = load_tournament(tournament_id)
    if tournament["status"] == "started":
        flash("This tournament has already started.", "error")
        return redirect(url_for("dashboard", tournament_id=tournament_id))

    teams = load_teams(tournament_id)
    schedule = build_schedule(teams, tournament["num_courts"], tournament["allow_repetition"] == 1)
    if len(schedule) == 0:
        flash("Cannot start yet: a league needs at least 2 teams to make a game.", "error")
        return redirect(url_for("dashboard", tournament_id=tournament_id))

    # Teams that are alone in their league get no games: warn the manager
    for league in load_leagues(tournament_id):
        in_league = [team["team_name"] for team in teams if team["league_id"] == league["league_id"]]
        if len(in_league) == 1:
            flash("Note: '" + in_league[0] + "' is the only team in the " + league["name"]
                  + " league and has no games.", "error")

    number_of_batches = count_batches(schedule)
    game_minutes = timing.calculate_game_minutes(tournament["expected_minutes"], number_of_batches)

    db = get_db()
    db.execute(
        "UPDATE tournaments SET status = 'started', started_at = ?, game_minutes = ?, current_batch = 1 "
        "WHERE tournament_id = ?",
        (timing.now_text(), game_minutes, tournament_id),
    )
    insert_games(tournament_id, schedule)
    db.commit()
    refresh_estimated_times(tournament_id)
    flash("The tournament has started! " + str(len(schedule)) + " games in "
          + str(number_of_batches) + " batches.", "success")
    return redirect(url_for("dashboard", tournament_id=tournament_id, batch=1) + "#schedule")


# ===========================================================================
# The batch slides (loaded only when somebody opens them)
# ===========================================================================

@app.route("/tournament/<int:tournament_id>/batch/<int:batch>")
def batch_slide(tournament_id, batch):
    tournament = load_tournament(tournament_id)
    names = make_team_name_list(load_teams(tournament_id))
    games = get_db().execute(
        "SELECT * FROM games WHERE tournament_id = ? AND batch = ? ORDER BY court",
        (tournament_id, batch),
    ).fetchall()

    # One entry per court: the game on it, or None if the court is free
    courts = []
    for court_number in range(1, tournament["num_courts"] + 1):
        game_on_court = None
        for game in games:
            if game["court"] == court_number:
                game_on_court = game
        courts.append((court_number, game_on_court))

    real_start = get_db().execute(
        "SELECT actual_start FROM batch_times WHERE tournament_id = ? AND batch = ?",
        (tournament_id, batch),
    ).fetchone()
    start_text = None
    if real_start is not None:
        start_text = real_start["actual_start"]
    elif len(games) > 0:
        start_text = games[0]["estimated_start"]

    return render_template(
        "batch_slide.html",
        tournament=tournament,
        league_names=make_league_name_list(load_leagues(tournament_id)),
        batch=batch,
        courts=courts,
        names=names,
        start_text=start_text,
        is_real_time=real_start is not None,
    )


@app.route("/tournament/<int:tournament_id>/batch/<int:batch>/time", methods=["POST"])
def update_batch_time(tournament_id, batch):
    """'Update time': the manager tells us when a batch really started."""
    if not is_manager():
        abort(403)
    tournament = load_tournament(tournament_id)
    if tournament["status"] != "started":
        abort(400)

    dashboard_page = url_for("dashboard", tournament_id=tournament_id, batch=batch) + "#schedule"
    clock_time = read_clock_time(request.form.get("time", ""))
    if clock_time is None:
        flash("Please pick a valid time.", "error")
        return go_back(dashboard_page)

    real_start = time_on_tournament_day(tournament, clock_time[0], clock_time[1])
    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO batch_times (tournament_id, batch, actual_start) VALUES (?, ?, ?)",
        (tournament_id, batch, real_start),
    )
    db.commit()
    refresh_estimated_times(tournament_id)
    flash("Batch " + str(batch) + " started at " + real_start[11:] + ". The next batches were recalculated.", "success")
    return go_back(dashboard_page)


@app.route("/tournament/<int:tournament_id>/batch/<int:batch>/make-current", methods=["POST"])
def make_current_batch(tournament_id, batch):
    """'Make current batch': the manager says this batch is the one being played now."""
    if not is_manager():
        abort(403)
    load_tournament(tournament_id)
    exists = get_db().execute(
        "SELECT COUNT(*) FROM games WHERE tournament_id = ? AND batch = ?", (tournament_id, batch)
    ).fetchone()[0]
    if exists == 0:
        flash("Batch " + str(batch) + " does not exist.", "error")
    else:
        get_db().execute("UPDATE tournaments SET current_batch = ? WHERE tournament_id = ?",
                         (batch, tournament_id))
        get_db().commit()
        flash("Batch " + str(batch) + " is now the current batch.", "success")
    return go_back(url_for("dashboard", tournament_id=tournament_id, batch=batch) + "#schedule")


# ===========================================================================
# Clicking on a court: add a result or change the batch
# ===========================================================================

@app.route("/game/<int:game_id>/options")
def game_options(game_id):
    if not is_manager():
        abort(403)
    game = load_game(game_id)
    tournament = load_tournament(game["tournament_id"])
    names = make_team_name_list(load_teams(tournament["tournament_id"]))

    # Group the possible moves per target batch, so the page can show them nicely
    moves_per_batch = []        # list of (target batch, [options])
    all_games = load_games(tournament["tournament_id"])
    if not game["finished"]:
        moves = find_batch_moves(game, all_games, tournament["current_batch"], tournament["num_courts"])
        for move in moves:
            if len(moves_per_batch) == 0 or moves_per_batch[-1][0] != move["target_batch"]:
                moves_per_batch.append((move["target_batch"], []))
            moves_per_batch[-1][1].append(move)

    # 'next' = the page to return to after saving (e.g. the team history page)
    next_page = request.args.get("next", "")
    if not (next_page.startswith("/") and not next_page.startswith("//")):
        next_page = ""

    return render_template("game_options.html", game=game, tournament=tournament,
                           league_names=make_league_name_list(load_leagues(tournament["tournament_id"])),
                           names=names, moves_per_batch=moves_per_batch,
                           last_batch=count_batches(all_games), next_page=next_page)


@app.route("/game/<int:game_id>/result", methods=["POST"])
def save_result(game_id):
    if not is_manager():
        abort(403)
    game = load_game(game_id)
    tournament = load_tournament(game["tournament_id"])
    back = url_for("dashboard", tournament_id=game["tournament_id"], batch=game["batch"]) + "#schedule"

    score1 = read_whole_number(request.form.get("score1", ""), 0)
    score2 = read_whole_number(request.form.get("score2", ""), 0)
    if score1 is None or score2 is None:
        flash("Scores must be whole numbers (0 or more).", "error")
        return go_back(back)
    if score1 == score2:
        flash("A badminton game cannot end in a draw. Please check the score.", "error")
        return go_back(back)

    # When did the game end? The manager may type a time; otherwise:
    #   a game that is finished now gets the current time,
    #   a score correction keeps the old end time.
    ended_text = request.form.get("ended_at", "").strip()
    if ended_text != "":
        clock_time = read_clock_time(ended_text)
        if clock_time is None:
            flash("The end time is not a valid time.", "error")
            return go_back(back)
        finished_at = time_on_tournament_day(tournament, clock_time[0], clock_time[1])
    elif game["finished"]:
        finished_at = game["finished_at"]
    else:
        finished_at = timing.now_text()

    db = get_db()
    if game["finished"]:
        # After "Finish game" only the score (and its end time) can still be corrected
        db.execute("UPDATE games SET score1 = ?, score2 = ?, finished_at = ? WHERE game_id = ?",
                   (score1, score2, finished_at, game_id))
        flash("Score corrected.", "success")
    else:
        db.execute("UPDATE games SET score1 = ?, score2 = ?, finished = 1, finished_at = ? WHERE game_id = ?",
                   (score1, score2, finished_at, game_id))
        # The current batch = the batch of the game that got the last score
        db.execute("UPDATE tournaments SET current_batch = ? WHERE tournament_id = ?",
                   (game["batch"], game["tournament_id"]))
        flash("Game finished. The ranking has been updated.", "success")
    db.commit()
    return go_back(back)


@app.route("/game/<int:game_id>/move", methods=["POST"])
def move_game(game_id):
    if not is_manager():
        abort(403)
    game = load_game(game_id)
    tournament = load_tournament(game["tournament_id"])
    tournament_id = tournament["tournament_id"]
    if game["finished"]:
        flash("A finished game cannot be moved.", "error")
        return go_back(url_for("dashboard", tournament_id=tournament_id, batch=game["batch"]) + "#schedule")

    target = read_whole_number(request.form.get("target_batch", ""), 1)
    swap_id = request.form.get("swap_game_id", "")

    # Check again that the chosen move is still allowed (someone else could
    # have changed the schedule in the meantime)
    chosen = None
    for option in find_batch_moves(game, load_games(tournament_id),
                                   tournament["current_batch"], tournament["num_courts"]):
        if option["target_batch"] != target:
            continue
        if option["swap_game"] is None and swap_id == "":
            chosen = option
        elif option["swap_game"] is not None and str(option["swap_game"]["game_id"]) == swap_id:
            chosen = option
    if chosen is None:
        flash("That move is not possible (anymore).", "error")
        return go_back(url_for("dashboard", tournament_id=tournament_id, batch=game["batch"]) + "#schedule")

    db = get_db()
    if chosen["swap_game"] is not None:
        # The other game goes to our old batch and court
        db.execute("UPDATE games SET batch = ?, court = ? WHERE game_id = ?",
                   (game["batch"], game["court"], chosen["swap_game"]["game_id"]))
    db.execute("UPDATE games SET batch = ?, court = ? WHERE game_id = ?",
               (target, chosen["court"], game_id))
    db.commit()

    new_numbers = remove_empty_batches(tournament_id)
    refresh_estimated_times(tournament_id)
    new_batch = new_numbers.get(target, target)
    flash("Game moved to batch " + str(new_batch) + ".", "success")
    return go_back(url_for("dashboard", tournament_id=tournament_id, batch=new_batch) + "#schedule")


# ===========================================================================
# Team history: all matches of one team
# ===========================================================================

@app.route("/team/<int:team_id>")
def team_history(team_id):
    team = load_team(team_id)
    tournament_id = team["tournament_id"]
    tournament = load_tournament(tournament_id)
    teams = load_teams(tournament_id)
    games = load_games(tournament_id)
    names = make_team_name_list(teams)

    # The team's line in the ranking (position, points, ...)
    ranking = build_ranking(teams, games)
    ranking_line = None
    for line in ranking.get(team["league_id"], []):
        if line["team_id"] == team_id:
            ranking_line = line

    # Batches whose real start time was set with "Update start time"
    real_start_batches = []
    for row in get_db().execute(
        "SELECT batch FROM batch_times WHERE tournament_id = ?", (tournament_id,)
    ).fetchall():
        real_start_batches.append(row["batch"])

    # One entry per match of this team, seen from this team's side
    matches = []
    for game in games:
        if game["team1_id"] == team_id:
            my_score = game["score1"]
            their_score = game["score2"]
            opponent_id = game["team2_id"]
        elif game["team2_id"] == team_id:
            my_score = game["score2"]
            their_score = game["score1"]
            opponent_id = game["team1_id"]
        else:
            continue  # this team does not play in this game

        result = None                     # None = not played yet
        if game["finished"]:
            if my_score > their_score:
                result = "won"
            else:
                result = "lost"

        matches.append({
            "game": game,
            "opponent_id": opponent_id,
            "opponent_name": names.get(opponent_id, "?"),
            "my_score": my_score,
            "their_score": their_score,
            "start": game["estimated_start"],
            "start_is_real": game["batch"] in real_start_batches,
            "ended": game["finished_at"],
            "result": result,
        })

    league_name = make_league_name_list(load_leagues(tournament_id)).get(team["league_id"], "")
    finished_games = 0
    for match in matches:
        if match["result"]:
            finished_games = finished_games + 1
    return render_template("team.html", team=team, tournament=tournament, league_name=league_name,
                           ranking_line=ranking_line, matches=matches, finished_games=finished_games)


# ===========================================================================
# Error pages
# ===========================================================================

@app.errorhandler(404)
def page_not_found(error):
    return render_template("message.html", title="Page not found",
                           message="This page or tournament does not exist."), 404


@app.errorhandler(403)
def not_allowed(error):
    return render_template("message.html", title="Managers only",
                           message="Please log in as a manager to do this."), 403


if __name__ == "__main__":
    # debug=True: the site reloads by itself when you change the code.
    # Only for running on your own computer! On a server, use waitress (see README.md).
    app.run(host="127.0.0.1", port=5000, debug=True)
