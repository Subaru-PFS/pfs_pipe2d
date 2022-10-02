import argparse
import datetime
import dbm
import io
import os
import re
from collections import defaultdict
from html import escape as hescape
from typing import Dict, Set, Tuple
from urllib.error import HTTPError

import lsst.log
import requests
from github import Github
from pfs.pipe2d.jenkins.github import getGithubAuth

logger = lsst.log.Log.getLogger("pfs.pipe2d.git_changelog")

JIRA_TICKET_CACHE = os.path.join(os.environ["HOME"], ".pfs", "ticket.cache")
"""Location of JIRA ticket cache
"""

JIRA_API_URL = r"https://pfspipe.ipmu.jp/jira/rest/api/2"
"""URL for JIRA REST API. For accessing ticket information (`str`)
"""

JIRA_URL = r"https://pfspipe.ipmu.jp/jira"
"""URL for JIRA tickets. For providing hyperlinks in output changelog (`str`)
"""

GITHUB_ORGANIZATION = "Subaru-PFS"
"""Name of organization as specified in Github (`str`)
"""

MERGE_MESSAGE_REGEX = re.compile(
    r"^.*tickets\/([A-Za-z0-9]+\-[0-9]+)\'?$", re.IGNORECASE
)
"""Merged message regular expression (`re.Pattern`).
The regular expression of the standard message generated when a ticket branch
is merged to master.
"""

TAG_REGEX = re.compile(r"^w\.(\d{4})\.(\d{2})$")
"""Git tag regular expression (`re.Pattern`).
The format of a tag. In the above case, for weeklies eg w.2022.17 .
"""

NOT_TAGGED = "NOT-TAGGED"
"""Label for tickets not assigned to a tag (`str`).
For grouping recently closed tickets that are not in a release, so not tagged.
"""


def getCommitMessage(commit) -> str:
    """Returns the corresponding message for the given commit.

    Parameters
    ----------
    commit: `github.Commit.Commit`
        Represents a git commit

    Returns
    -------
    message: `str`
        Commit message
    """
    return commit.raw_data["commit"]["message"]


def getTicketsForTags(repo, branchName: str, shaTag) -> "Dict[str, Set[str]]":
    """Gets the mapping of tag name to set of ticket names for the given repository.

    Parameters
    ----------
    repo: `github.Repository.Repository`
        Represents a git repository
    branchName: `str`
        Name of branch
    shaTag: `dict` [`int`, `str`]
        mapping of commit sha to tag name

    Returns
    -------
    tagTickets: `dict` [`str`, `set`[`str`]]
        mapping of tag name to a set of corresponding ticket names
    """
    branch = repo.get_branch(branchName)
    commit = branch.commit

    tagTickets = {}
    currentTag = NOT_TAGGED

    tickets: Set[str] = set()

    # From the HEAD commit node, traverse up the commit tree,
    # finding nodes where a ticket branch has been merged to master
    # along the way. Record the corresponding JIRA tickets and bounding commit tags.
    while True:
        sha = commit.sha
        if sha in shaTag:
            logger.debug(
                f"{repo.full_name}: Found tag {shaTag[sha]} " f"for commit {sha}"
            )
            tagTickets[currentTag] = tickets
            currentTag = shaTag[sha]
            tickets = set()
        message = getCommitMessage(commit)
        m = MERGE_MESSAGE_REGEX.match(message)
        if m and len(m.groups()) == 1:
            ticketName = m.group(1)
            logger.debug(f"Found ticket [{ticketName}] from message [{message}]")
            tickets.add(ticketName)
        else:
            logger.debug(f"No ticket found from message [{message}].")
        if len(commit.parents) == 0:
            break
        # Choose the single parent, or in the case of multiple parents, the first parent.
        # This works for multiple parents given the assumption that the merge graph is 'clean'
        # in the sense that:
        # a) all ticket branches are merged to master, and
        # b) ticket branches are rebased such that any given ticket branch
        # is merged _before_ a new ticket branch is created.
        # As efforts are made to enforce this in DRP,
        # any branch traversed will hit the ticket branch merge nodes.
        commit = commit.parents[0]

    return tagTickets


def getShaForTag(repo) -> "Dict[int, str]":
    """Gets the mapping of sha to tag name for the input repository.

    Parameters
    ----------
    repo: `github.Repository.Repository`
        Represents a git repository

    Returns
    -------
    sha_tag: `dict` [`int`, `str`]
        mapping of commit sha to tag name
    """
    return {
        tag.commit.sha: tag.name for tag in repo.get_tags() if TAG_REGEX.match(tag.name)
    }


def updateChangeLog(
    github, branchName: str, changeLog: "Dict[str, Dict[str, Set[str]]]", repoName: str
) -> None:
    """Updates the working changelog object with the ticket information
    found in the input repository.

    Parameters
    ----------
    github : `github.MainClass.Github`
        Mediates requests to GitHub API.
    branchName : `str`
        Name of git branch to view.
    repoName : `str`
        Name of the github repository to read
    changeLog : `dict` [`str`, `dict` [`str`, `set` [`str`] ] ]
        Maps a git tag to a ticket, and to a set of
        repositories that have been updated for that
        ticket.
    """
    repo = github.get_repo(f"{GITHUB_ORGANIZATION}/{repoName}")

    shaTag = getShaForTag(repo)
    tag_tickets = getTicketsForTags(repo, branchName, shaTag)

    for tag, tickets in tag_tickets.items():
        if tag not in changeLog:
            changeLog[tag] = defaultdict(set)

        for ticket in tickets:
            changeLog[tag][ticket].add(repoName)


def generateChangeLog(
    github, branch: str, repoNames: "Set[str]"
) -> "Dict[str, Dict[str, Set[str]]]":
    """Query the GitHub API for the given repository
    and construct a mapping between git tags and JIRA tickets.

    Parameters
    ----------
    github : `github.MainClass.Github`
        Mediates requests to GitHub API.
    branch : `str`
        Name of git branch to view.
    repoNames : `set` [`str`]
        Names of the github repositories.

    Returns
    -------
    changeLog : `dict` [`str`, `dict` [`str`, `set` [`str`] ] ]
        Maps a git tag to a ticket, and to a set of
        repositories that have been updated for that
        ticket.
    """

    changeLog: Dict[str, Dict[str, Set[str]]] = {}
    for repoName in repoNames:
        logger.info(f"Processing repo {repoName}...")
        updateChangeLog(github, branch, changeLog, repoName)
    return changeLog


def getTicketSummary(ticket: str) -> str:
    """Extracts summary of ticket from an external source (eg JIRA).

    Parameters
    ----------
    ticket : `str`
        Ticket identifier.

    Returns
    -------
    summary : `str`
        ticket summary.
    """
    db = dbm.open(JIRA_TICKET_CACHE, "c")
    try:
        if ticket not in db:
            url = f"{JIRA_API_URL}/issue/{ticket}?fields=summary"
            logger.debug(f"JIRA URL = {url}")
            data = requests.get(url).json()
            if "fields" not in data:
                logger.warning(f"Cannot find any information for ticket {ticket}")
                raise ValueError(f"Description for ticket {ticket} not available")
            db[ticket] = data["fields"]["summary"].encode("UTF-8")
        # json gives us a unicode string, which we need to encode for storing
        # in the database, then decode again when we load it.
        return db[ticket].decode("UTF-8")
    except HTTPError as e:
        raise ValueError(f"Description for ticket {ticket} not available") from e
    finally:
        db.close()


def writeTagSummary(
    writer: io.TextIOWrapper, tagname: str, ticketRepos: "Dict[str, Set[str]]"
) -> None:
    """Write ticket summaries for a given tag to output

    Parameters
    ----------
    writer : `io.TextIOWrapper`
        output writer
    tagname : `str`
        name of release tag
    ticketRepos : `dict` [`str, `set` [`str`]]
        mapping of tickets to repos
    """
    if tagname == NOT_TAGGED:
        writer.write("<h2>Not tagged</h2>\n")
    else:
        writer.write(f"<h2>New in {hescape(tagname)}</h2>\n")

    writer.write("<ul>\n")
    if not ticketRepos:
        writer.write("<li><i>None</i></li>\n")
    else:
        for ticket in sorted(ticketRepos):
            summary = getTicketSummary(ticket)
            pkgs = ", ".join(sorted(ticketRepos[ticket]))
            linkText = (
                f"<li><a href={JIRA_URL}/browse/"
                f"{ticket}>{ticket}</a>: "
                f"{hescape(summary)} [{hescape(pkgs)}]</li>\n"
            )
            writer.write(
                linkText.format(ticket=ticket.upper(), summary=summary, pkgs=pkgs)
            )
    writer.write("</ul>\n")


def tagKey(tagname: str) -> Tuple[int, ...]:
    """Converts a tagname ("w.YYYY.WW") into a key for sorting.

    Parameters
    ----------
    tagname : `str`
        name of release tag

    Returns
    -------
    sortKey : tuple[`int`, ...]
        numerical key for sorting.
    """
    return tuple(int(i) for i in tagname[2:].split("."))


def writeHtml(
    changelog: "Dict[str, Dict[str, Set[str]]]", repositories: "Set[str]", outfile: str
) -> None:
    """Write changelog to file in HTML format

    Parameters
    ----------
    changelog : `dict` [`str`, `dict` [`str`, `set` [`str`]]]
        mapping of tag to ticket identifiers.
    repositories: `set` [`str`]
        list of git repositories
    outfile: `str`
        the name of the output file
    """
    # FIXME: Needs a proper templating engine
    with open(outfile, "w") as writer:
        writer.write("<html>\n")
        writer.write("<head><title>PFS Changelog</title></head>\n")
        writer.write("<body>\n")
        writer.write("<h1>PFS 2D DRP Changelog</h1>\n")

        # Always do the not-in-tag tickets first if they exist.
        if NOT_TAGGED in changelog:
            writeTagSummary(writer, NOT_TAGGED, changelog.pop(NOT_TAGGED))

        # Then the other tags in order
        for tag in sorted(changelog, reverse=True, key=tagKey):
            writeTagSummary(writer, tag, changelog[tag])

        gen_date = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M +00:00")
        repos = ", ".join(os.path.basename(r) for r in sorted(repositories))
        writer.write(
            f"<p>Generated at {hescape(gen_date)} "
            "based on the following"
            f" repositories: {hescape(repos)}.</p>\n"
        )
        writer.write("</body>\n")
        writer.write("</html>\n")


def process(args: argparse.Namespace) -> None:
    """Process the command line arguments and generate the changelog

    Parameters
    ----------
    args : `'argparse.Namespace'`
        command-line arguments
    """
    # Handle logging level
    if args.loglevel is not None:
        logLevel = getattr(lsst.log.Log, args.loglevel.upper())
        logger.setLevel(logLevel)

    # Check that repository names are valid
    repoRegex = "^[A-Za-z0-9_]+$"
    repositories = {rr for rr in args.repositories if re.match(repoRegex, rr)}
    if set(repositories) != set(args.repositories):
        badRepos = set(args.repositories) - set(repositories)
        logger.fatal(
            f'repositories "{badRepos}"'
            f' does not match format "{repoRegex}"".'
            " Exiting."
        )
        exit(1)

    branch = "master"

    # Access github generated access token
    access_token = getGithubAuth()[1]

    # login with access token
    g = Github(access_token)

    logger.info("Generating change log...")
    changeLog = generateChangeLog(g, branch, repositories)
    logger.info("Writing HTML...")
    writeHtml(changeLog, repositories, args.outfile)
    logger.info("Processing COMPLETE. " f'Changelog written to file "{args.outfile}".')


def main() -> None:
    """Parse and process command-line arguments and generate the changelog"""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "repositories",
        nargs="+",
        help=(
            "list of repositories. "
            "This needs to contain pfs_utils "
            "to determine tag-ticket assignment."
        ),
    )
    parser.add_argument(
        "--outfile", "-o", default="changelog.html", help="name of output file"
    )
    parser.add_argument(
        "--loglevel",
        "-L",
        choices=["trace", "debug", "info", "warn", "error", "fatal"],
        help=("logging level"),
    )

    args = parser.parse_args()
    process(args)


if __name__ == "__main__":
    main()
