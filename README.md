# BSC Leiden – Badminton tournament manager

A small website to run badminton tournaments:

* **Everybody** can browse the tournaments, the schedule, the courts and the ranking (no login).
* **Managers** log in to create tournaments, add teams, start a tournament, enter
  scores, move games to another batch and update batch start times.

Built with plain Python: **Flask** (web pages) and **SQLite** (a database in one file).

## Project files

| File / folder        | What it does                                                         |
|----------------------|----------------------------------------------------------------------|
| `app.py`             | All pages and buttons                                                |
| `database.py`        | The tables (`tournaments`, `leagues`, `teams`, `games`, `batch_times`, `managers`) |
| `scheduler.py`       | Builds the concept schedule and the "Change batch" options           |
| `ranking.py`         | `game_points()`: win = 2, loss = 0. Change this one function to change the ranking |
| `timing.py`          | Time per game (3 min break between games) and estimated start times  |
| `create_manager.py`  | Add a manager or change a password                                   |
| `templates/`         | HTML pages                                                           |
| `static/`            | Style sheet, JavaScript and the BSC logo                             |

## Run it on your own computer

```bash
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000 in your browser.

The first time you run it, a manager account is created automatically:
**username `admin`, password `admin`**. Change it straight away:

```bash
python create_manager.py
```

(Run the same command to add more managers.)

The data is stored in `badminton.db` next to `app.py`. Delete that file to start with an empty website.

## How a tournament works

1. Log in, click **+ Add tournament** and fill in the form. Choose the leagues (default: Beginner, Intermediate, Advanced).
2. On the dashboard, click **+ Add teams**. Use **+ Add another team** to add more rows.
3. Click **START tournament**. The concept schedule is built: every team plays every other team
   of its own league, no team plays twice in one batch, and the waiting time is spread evenly.
4. Open a batch in **Schedule**. Click a court to add a score (**Finish game**) or to move the
   game to another batch. Use **Update time** to record when a batch really started; the
   following batches are recalculated.
5. You can still add teams after the start. Games that are not played yet are planned again;
   results are never lost.
6. Click **✎ Edit** next to a team (dashboard → Teams, or on the team's own page) to change its
   name or members. Games and rankings only store the team number, so the new name shows up
   everywhere straight away. A team can move to another league only until it has finished a game.
7. **✕ Remove team** also works after the start (e.g. somebody went home). All games of that team
   are deleted and the rest of the schedule is planned again. Its finished games no longer count
   for the ranking, so every team in the league is treated the same.
8. The **Expected end** tile on the dashboard shows when the last game should end. It is updated
   with every "Update time" and every change to the schedule, and says how late you are compared
   to the planned duration.

## Settings (environment variables)

| Variable         | Default                 | Meaning                                         |
|------------------|-------------------------|-------------------------------------------------|
| `SECRET_KEY`     | a development key       | **Set a long random text on a server!**         |
| `ADMIN_PASSWORD` | `admin`                 | Password for the first `admin` account (only used when no manager exists yet) |
| `DATABASE_PATH`  | `badminton.db` here     | Where the database file is stored               |
| `TIMEZONE`       | `Europe/Amsterdam`      | Time zone used for the start times              |

## Putting it online (e.g. Scaleway)

`python app.py` is only meant for your own computer. On a server, use the included
`Dockerfile`, which runs the site with **waitress** (a production web server written in Python).

The simplest option is a small **Scaleway Instance** (a virtual server) with Docker installed:

```bash
# on the server, inside a copy of this folder
docker build -t bsc-tournaments .
docker run -d --restart unless-stopped -p 80:8080 \
    -v bsc-data:/data \
    -e SECRET_KEY="put-a-long-random-text-here" \
    -e ADMIN_PASSWORD="a-strong-password" \
    bsc-tournaments
```

The `-v bsc-data:/data` part keeps the database when the container is restarted or updated.
To make a long random secret key, run: `python -c "import secrets; print(secrets.token_hex(32))"`.

Without Docker it also works: `pip install -r requirements.txt` and then
`waitress-serve --host=0.0.0.0 --port=8080 app:app`.

> **Note:** Scaleway *Serverless Containers* do not keep files between restarts, so the
> SQLite database would be lost there. Use an Instance (as above), or switch the database to a
> Scaleway Managed PostgreSQL database (only `database.py` would need to change).

For a public website, also add HTTPS (for example with Caddy or nginx in front of the container)
so manager passwords are never sent unencrypted.
