"""Send one test alert email to OWNER_EMAIL:  python -m jobs.email_test"""

from tracker import config
from tracker.emailer import GmailSender, Item, compose


def main() -> None:
    if not config.OWNER_EMAIL:
        raise SystemExit("Set OWNER_EMAIL in .env first.")
    msg = compose(config.OWNER_EMAIL, [Item("Test: email alerts work",
                                            "This is a test from Stock Tracker. Real alerts look like this, with a short note and a link.",
                                            f"{config.BASE_URL}/alerts")])
    with GmailSender() as g:
        g.send(msg)
    print(f"sent a test email from {config.SMTP_USER} to {config.OWNER_EMAIL}")


if __name__ == "__main__":
    main()
