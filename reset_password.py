"""Reset an Omnipuls password from the computer that runs the app.

Usage (in the app folder):  .venv\\Scripts\\python reset_password.py
It lists the accounts, asks which one, and sets a new password. Only someone
with access to this computer's files can run it, which is what keeps it safe.
"""
import getpass

import auth


def main():
    users = auth.load()
    if not users:
        print("No accounts yet. Start Omnipuls and create the admin account on the sign-in screen.")
        return
    print("Accounts:")
    for uid, u in sorted(users.items()):
        print(f"  {uid}  ({u['role']})")
    uid = auth.normalize(input("User ID to reset: "))
    if uid not in users:
        print("No such user.")
        return
    while True:
        pw = getpass.getpass("New password: ")
        if pw != getpass.getpass("Repeat new password: "):
            print("The passwords don't match. Try again.")
            continue
        err = auth.set_password(uid, pw)
        if err:
            print(err)
            continue
        print(f"Password for {uid} changed. Sign in with the new password.")
        return


if __name__ == "__main__":
    main()
