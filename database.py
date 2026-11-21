"""
database.py - everything about storing data.

We use SQLite, a database that lives in a single file (badminton.db).
It comes with Python, so nothing extra has to be installed.

To move the website to a server (for example Scaleway) you only have to make
sure the DATABASE_PATH environment variable points to a folder that is kept
when the server restarts (see README.md).
"""

import os
import shutil
import sqlite3

from flask import g

# Folder where this file lives. The database file is stored next to it,
# unless the DATABASE_PATH environment variable says otherwise.
THIS_FOLDER = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.environ.get("DATABASE_PATH", os.path.join(THIS_FOLDER, "badminton.db"))


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------
# tournaments  : one row per tournament (tournament_id is the key)
# leagues      : the leagues of a tournament (e.g. Beginner, Intermediate, Advanced)
# teams        : one row per team, linked to a tournament and to a league
# games        : the schedule ("concept schedule"): batch, court, team 1, team 2,
#                estimated start time and the score
# batch_times  : the real start time of a batch, filled in by a manager
#                with the "Update time" button
# managers     : people that are allowed to log in and change things
SCHEMA = """
CREATE TABLE IF NOT EXISTS managers (
    manager_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    username       TEXT UNIQUE NOT NULL,
    password_hash  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tournaments (
    tournament_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,
    date              TEXT NOT NULL,                  -- 'YYYY-MM-DD'
    game_type         TEXT NOT NULL,                  -- 'singles' or 'doubles'
    num_courts        INTEGER NOT NULL,
    expected_people   INTEGER NOT NULL,
    expected_minutes  INTEGER NOT NULL,               -- how long the whole tournament should last
    allow_repetition  INTEGER NOT NULL DEFAULT 0,     -- 1 = teams may meet more than once
    status            TEXT NOT NULL DEFAULT 'preparing',  -- 'preparing' or 'started'
    started_at        TEXT,                           -- 'YYYY-MM-DD HH:MM', set by START button
    game_minutes      INTEGER,                        -- planned length of one game, set by START
    current_batch     INTEGER NOT NULL DEFAULT 1      -- batch of the last game that got a score
);

CREATE TABLE IF NOT EXISTS leagues (
    league_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id  INTEGER NOT NULL REFERENCES tournaments(tournament_id) ON DELETE CASCADE,
    name           TEXT NOT NULL,                     -- e.g. 'Beginner'
    position       INTEGER NOT NULL                   -- order on the website: 1, 2, 3, ...
);

CREATE TABLE IF NOT EXISTS teams (
    team_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id  INTEGER NOT NULL REFERENCES tournaments(tournament_id) ON DELETE CASCADE,
    team_name      TEXT NOT NULL,
    member1        TEXT NOT NULL,
    member2        TEXT,                              -- empty for singles
    league_id      INTEGER NOT NULL REFERENCES leagues(league_id)
);

CREATE TABLE IF NOT EXISTS games (
    game_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id    INTEGER NOT NULL REFERENCES tournaments(tournament_id) ON DELETE CASCADE,
    batch            INTEGER NOT NULL,
    court            INTEGER NOT NULL,
    team1_id         INTEGER NOT NULL REFERENCES teams(team_id),
    team2_id         INTEGER NOT NULL REFERENCES teams(team_id),
    league_id        INTEGER NOT NULL,                -- both teams are in this league
    estimated_start  TEXT,                            -- 'YYYY-MM-DD HH:MM'
    score1           INTEGER,                         -- score of team 1 (empty until played)
    score2           INTEGER,                         -- score of team 2
    finished         INTEGER NOT NULL DEFAULT 0,      -- status: 0 = planned, 1 = finished
    finished_at      TEXT                             -- 'YYYY-MM-DD HH:MM' when the score was added (game ended)
);

CREATE TABLE IF NOT EXISTS batch_times (
    tournament_id  INTEGER NOT NULL REFERENCES tournaments(tournament_id) ON DELETE CASCADE,
    batch          INTEGER NOT NULL,
    actual_start   TEXT NOT NULL,                     -- 'YYYY-MM-DD HH:MM'
    PRIMARY KEY (tournament_id, batch)
);
"""


def open_connection():
    """Open a new connection to the database file."""
    connection = sqlite3.connect(DATABASE_PATH)
    # Row lets us write row["name"] instead of row[1]
    connection.row_factory = sqlite3.Row
    # SQLite only checks the REFERENCES (links between tables) when this is on
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def get_db():
    """
    Give back the database connection for the current web request.
    Flask's 'g' object lives for exactly one request, so every page visit
    gets its own connection, which is closed again by close_db().
    """
    if "db" not in g:
        g.db = open_connection()
    return g.db


def close_db(error=None):
    """Close the connection at the end of a request (called by Flask)."""
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def create_tables():
    """Create the tables if they do not exist yet. Safe to run every time."""
    folder = os.path.dirname(DATABASE_PATH)
    if folder and not os.path.exists(folder):
        os.makedirs(folder)
    connection = open_connection()
    connection.executescript(SCHEMA)
    add_missing_columns(connection)
    connection.commit()
    move_divisions_to_leagues(connection)
    connection.close()


def column_names(connection, table):
    """The names of all columns of a table."""
    names = []
    for row in connection.execute("PRAGMA table_info(" + table + ")").fetchall():
        names.append(row["name"])
    return names


def add_missing_columns(connection):
    """
    "CREATE TABLE IF NOT EXISTS" does not change tables that already exist.
    When a new column is added to the website later on, we add it here to
    older database files, so nobody loses their data.
    """
    if "finished_at" not in column_names(connection, "games"):
        connection.execute("ALTER TABLE games ADD COLUMN finished_at TEXT")


def move_divisions_to_leagues(connection):
    """
    Older versions of the website had 3 fixed divisions, stored as the numbers
    1, 2 and 3 in a 'division' column. Now every tournament has its own leagues
    (table 'leagues'). This converts an old database ONCE:
      * every tournament gets the leagues Beginner (1), Intermediate (2), Advanced (3)
      * the 'division' columns are renamed to 'league_id' and get the new ids
    A copy of the old database file is saved first (…db.before-leagues.bak).
    """
    if "division" not in column_names(connection, "teams"):
        return  # nothing to do: already converted (or a brand new database)

    shutil.copy(DATABASE_PATH, DATABASE_PATH + ".before-leagues.bak")
    old_names = {1: "Beginner", 2: "Intermediate", 3: "Advanced"}

    connection.execute("BEGIN")   # all or nothing: if anything fails, nothing changes
    try:
        for table in ("teams", "games"):
            if "division" in column_names(connection, table):
                connection.execute("ALTER TABLE " + table + " RENAME COLUMN division TO league_id")
                # Make the old numbers negative for a moment, so an old number can
                # never be mixed up with a new league id
                connection.execute("UPDATE " + table + " SET league_id = -league_id")

        for tournament in connection.execute("SELECT tournament_id FROM tournaments").fetchall():
            tournament_id = tournament["tournament_id"]
            for number in (1, 2, 3):
                cursor = connection.execute(
                    "INSERT INTO leagues (tournament_id, name, position) VALUES (?, ?, ?)",
                    (tournament_id, old_names[number], number),
                )
                for table in ("teams", "games"):
                    connection.execute(
                        "UPDATE " + table + " SET league_id = ? WHERE tournament_id = ? AND league_id = ?",
                        (cursor.lastrowid, tournament_id, -number),
                    )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
