"""
create_manager.py - add a manager account, or change the password of one.

Run it from this folder with:
    python create_manager.py
"""

from getpass import getpass

from werkzeug.security import generate_password_hash

import database


def main():
    database.create_tables()
    print("Add a manager (or give an existing username to change its password).")
    username = input("Username: ").strip()
    if username == "":
        print("No username given, nothing changed.")
        return

    password = getpass("Password (you will not see what you type): ")
    repeat = getpass("Password again: ")
    if password != repeat:
        print("The passwords are not the same, nothing changed.")
        return
    if len(password) < 6:
        print("Please use at least 6 characters, nothing changed.")
        return

    connection = database.open_connection()
    existing = connection.execute("SELECT * FROM managers WHERE username = ?", (username,)).fetchone()
    if existing is None:
        connection.execute("INSERT INTO managers (username, password_hash) VALUES (?, ?)",
                           (username, generate_password_hash(password)))
        print("Manager '" + username + "' created.")
    else:
        connection.execute("UPDATE managers SET password_hash = ? WHERE username = ?",
                           (generate_password_hash(password), username))
        print("Password of '" + username + "' changed.")
    connection.commit()
    connection.close()


if __name__ == "__main__":
    main()
