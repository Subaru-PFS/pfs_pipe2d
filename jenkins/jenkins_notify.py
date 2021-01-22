#!/usr/bin/env python

from pfs.pipe2d.jenkins.slack import postSlack
from pfs.pipe2d.jenkins.email import sendEmail
from pfs.pipe2d.jenkins.users import getUser


def jenkinsNotify(workdir, username, description, failed=None, disable=False):
    """Notify a user of the disposition of a Jenkins run

    We send a Slack message and an e-mail.

    Parameters
    ----------
    workdir : `str`
        Work directory for Jenkins run.
    username : `str`
        Username for originator of Jenkins run.
    description : `str`
        Description of Jenkins run (build number).
    failed : `str`, optional
        Jenkins state at failure, or ``None`` for success.
    disable : `bool`, optional
        Disable actually doing anything?
    """
    user = getUser(username)
    status = f"failed at {failed}" if failed else "was successful"
    slackMessage = f"<@{user.slack}>: Jenkins build {description} {status}. See `{workdir}` for results."
    emailMessage = f"Jenkins build {description} {status}. See {workdir} for results."
    postSlack(slackMessage, disable=disable)
    sendEmail(getUser().email, user.email, f"Jenkins build {description}", emailMessage, disable=disable)


def main():
    """Notify originator of Jenkins result"""
    from argparse import ArgumentParser
    parser = ArgumentParser(description="Notify originator of Jenkins result")
    parser.add_argument("--workdir", required=True, help="Work directory for Jenkins run")
    parser.add_argument("--username", required=True, help="Username for originator")
    parser.add_argument("--description", required=True, help="Description of the build")
    parser.add_argument("--failed", default=None, help="Jenkins state at failure; ")
    parser.add_argument("--disable", default=False, action="store_true",
                        help="Don't actually send/post anything?")
    args = parser.parse_args()
    return jenkinsNotify(**vars(args))


if __name__ == "__main__":
    main()
