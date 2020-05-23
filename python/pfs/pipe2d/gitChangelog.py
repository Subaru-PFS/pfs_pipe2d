from collections import defaultdict
from collections import OrderedDict
import datetime
import json
import os
import re
from urllib.request import urlopen
from urllib.error import HTTPError
import requests
import dbm
import argparse
import lsst.log
from configparser import ConfigParser
from html import escape as hescape
import getpass
from datetime.datetime import strptime

logger = lsst.log.Log.getLogger("pfs.pipe2d.git_changelog")

GITHUB_USER = {"pprice": "PaulPrice",
               "hassans": "hassanxp",
               "rhl": "RobertLuptonTheGood",
               "ncaplar": "nevencaplar",
               "craigl": "CraigLoomis",
               }
"""Princeton University netID to GitHub username mapping.
For GitHub authentication using internal network information
"""

GITHUB_AUTH = os.path.join(os.environ["HOME"], ".pfs", "github_api_token")
"""Location of GitHub API token for internal authentication
"""

JIRA_API_URL = r"https://pfspipe.ipmu.jp/jira/rest/api/2"
"""URL for JIRA REST API. For accessing ticket information (`str`)
"""

JIRA_URL = r"https://pfspipe.ipmu.jp/jira"
"""URL for JIRA tickets. For providing hyperlinks in output changelog (`str`)
"""

GITHUB_API_BASE_URL = r'https://api.github.com/repos/Subaru-PFS'
"""Base URL for GitHub REST API for querying GitHub API (`str`)
"""

GITHUB_API_MAX_PAGES = 20
""" Maximum number of pages retrieved per github api request (`int`).
When querying the GitHub REST API, the result is
provided across multiple pages.
While this must be finite, provide a limit to this.
"""

GITHUB_API_PARAMS = {'per_page': 100}
"""Github API request parameters (`dict`)
Limit the number of results per page in a REST API query to the above.
"""

RATE_LIMIT_URL = r'https://api.github.com/rate_limit'
"""The github request rate limit URL (`str`).
The allowed number of GITHUB API requests per hour for the user in question.
This is used to check if the number of requests have been exceeded so
that situation can be handled
(that is, an error message is raised and the program exits)
"""

GITHUB_API_TICKET_REGEX = r'^Subaru-PFS:tickets/([A-Z0-9]+-[0-9]+)$'
"""JIRA ticket regular expression (`str`).
The JIRA ticket name is stored in the GitHub API in the above
format. This is used to parse the ticket number.
"""

TAG_REGEX = r"^([0-9]+)\.([0-9]+)(\.[0-9]+)?$"
"""Git tag regular expression (`str`).
The format of a tag. In the above case, M.m[.p] for releases.
"""

NOT_TAGGED = 'NOT-TAGGED'
"""Label for tickets not assigned to a tag (`str`).
For grouping recently closed tickets that are not in a release, so not tagged.
"""


def _noAuthentication(authfile):
    """Handles situation where no GitHub API authentication
    is to be provided.

    Parameters
    ----------
    authfile : `str`
        File containing authentication credentials

    Returns
    -------
    auth : `tuple` (`set`, `set`)
        tuple to enable HTTP authentication
    """
    logger.debug('Using no authentication')
    return None


def _externalAuthentication(authfile):
    """Handles authentication being provided by an external file.

    Parameters
    ----------
    authfile : `str`
        File containing authentication credentials

    Returns
    -------
    auth : `tuple` (`set`, `set`)
        tuple to enable HTTP authentication
    """
    logger.debug('Authenticating using externally-supplied information')
    if authfile is None:
        logger.fatal('Need to supply a authentication file'
                     'to the --authfile argument')
        exit(1)
    logger.debug(f'Authenticating using file {authfile}')
    with open(authfile) as f:
        parser = ConfigParser()
        parser.read_file(f)
        return (parser['github']['user'], parser['github']['token'])


def _internalAuthentication(authfile):
    """Handles authentication being provided from the
    Princeton internal network.

    Parameters
    ----------
    authfile : `str`
        File containing authentication credentials

    Returns
    -------
    auth : `tuple` (`set`, `set`)
        tuple to enable HTTP authentication
    """
    logger.debug('Authenticating using internal information')
    return getGitHubAuth()


class Paginator:
    """Combines GitHub API REST v3 requests
    that are provided across multiple pages.

    Typically a call through the GitHub API
    will paginate the requested items
    to keep their servers happy.

    Parameters
    ----------
    params : `dict`
        Parameters in the query for the GitHub API request.
    auth : `tuple` (`set`, `set`)
        tuple to enable HTTP authentication
    max_pages : `int`
        The maximum number of pages to return from a single request.

    See also
    --------
    URL https://developer.github.com/v3/#pagination
    """
    def __init__(self, params, auth, max_pages):
        self.params = params
        self.auth = auth
        self.max_pages = max_pages

    def _getRequest(self, url):
        """ Retrieves HTTP request
            Parameters
            ----------
            url : `str`
                GitHub API URL to be accessed.

            Returns
            ------
            response : `list` [`dict`]
                The GitHub response for a single page.
        """ 
        return requests.get(url, params=self.params, auth=self.auth)

    def pages(self, url):
        """Iterates over pages from the provided URL

        Parameters
        ----------
        url : `str`
            GitHub API URL to be accessed.

        Yields
        ------
        response : `list` [`dict`]
            The GitHub response. Each element in the list
            corresponds to a separate page. The structure
            of each element depends on the GitHub API
            call.
        """
        for _ in range(self.max_pages):
            r = self._getRequest(url)
            yield json.loads(r.text)
            if 'next' in r.links:
                url = r.links['next']['url']
            else:
                return

    def retrieveRequestAsDict(self, url):
        """Returns the response from the provided URL, decoded from JSON.

        Parameters
        ----------
        url : `str`
            GitHub API URL to be accessed.

        Returns
        -------
        response : `dict`
            The GitHub response. The structure
            depends on the specific GitHub API
            request being made.
        """
        return self._getRequest(url).json()


class GitHubMediator:
    """Mediates requests with the GitHub API Server.

    Used to interact with a GitHub API server,
    returning the results of a request.
    Specific information needed from the server
    (tags, merged pull requests) are handled in
    this class.
    Pagination is also handled internally.

    Parameters
    ----------
    prefix_url : `str`
        URL prefix for GitHub API request
    params : `dict`
        Parameters in the query for the GitHub API request.
    auth : `tuple` (`str`, `str`)
        tuple to enable HTTP authentication
    max_pages : `int`
        The maximum number of pages to return from a single request.
    """
    def __init__(self, prefix_url, params, auth, max_pages):
        self.prefix_url = prefix_url
        self.paginator = Paginator(params, auth, max_pages)

    def getRateLimit(self):
        """Returns the rate limit (number of requests per hour)
        to the GitHub API server.
        """
        result = self.paginator.retrieveRequestAsDict(RATE_LIMIT_URL)
        return result

    def extractPulls(self, url):
        """Retrieves details of each pull request, returning
        those that have ticket information.

        Parameters
        ----------
        url : `str`
            The URL endpoint for pull requests.

        Returns
        -------
        ticket_date : `dict` (`str`: `str`)
            mapping of ticket ID to date
        """
        ticket_date = OrderedDict()
        pages = self.paginator.pages(url)
        for page in pages:
            for entry in page:
                label = entry['head']['label']
                timestamp = entry['merged_at']
                m = re.search(GITHUB_API_TICKET_REGEX, label)
                if m is not None:
                    ticket = m.group(1)
                    ticket_date[ticket] = timestamp
        return ticket_date

    def extractTags(self, url):
        """Retrieves details of each git tag

        Parameters
        ----------
        url : `str`
            The URL endpoint for requesting tag information.

        Returns
        -------
        tag_commit : `dict` (`str`: `list` [`str`])
            mapping of tag to commit sha
        """
        pattern = re.compile(TAG_REGEX)
        tag_commit = {}
        pages = self.paginator.pages(url)
        for page in pages:
            for entry in page:
                sha = entry['commit']['sha']
                name = entry['name']
                if not pattern.match(name):
                    logger.debug(f'Tag "{name}" '
                                 'doesnt match m.n.p or m.n formats. '
                                 'Skipping.')
                else:
                    tag_commit[name] = sha
        return tag_commit

    def extractCommits(self, url):
        """Retrieves merged commits

        Parameters
        ----------
        url : `str`
            The URL endpoint for requesting tag information.

        Returns
        -------
        commit_time : `dict` (`str`: `str`)
            Mapping of commit sha to timestamp
        """
        commit_time = {}
        pages = self.paginator.pages(url)
        for page in pages:
            for entry in page:
                sha = entry['sha']
                timestamp = entry['commit']['committer']['date']
                commit_time[sha] = timestamp
        return commit_time

    def tagToDate(self, tag_commit, commit_time):
        """Associates the timestamp of a tag to that tag

        Parameters
        ----------
        tag_commit : `dict` (`str`: `str`)
            mapping of tag to commit sha
        commit_time : `dict` (`str`: `str`)
            mapping of commit sha to timestamp

        Returns
        -------
        tag_date : `dict` (`str`: str`)
            mapping of tag to timestamp
        """
        tag_date = {}
        for tag in tag_commit:
            commit = tag_commit[tag]
            if commit in commit_time:
                tag_date[tag] = commit

    def tag_to_tickets(self, tag_date, ticket_date):
        """Relates the tag-to-date and ticket-to-date
        information to assign tickets to
        the appropriate tag.

        Parameters
        ----------
        tag_date : `dict` (`str`: `str`)
            mapping of tag to date
        ticket_date : `dict` (`str`: `str`)
            mapping of ticket to date

        Returns
        -------
        tag_tickets : `dict` (`str`: `list` [`str`])
            mapping of tag to corresponding tickets
        """
        tag_tickets = {}

        tag_daterange = {}
        prev_timestamp = None
        prev_tag = None
        for tag in tag_date:
            timestamp = tag_date[tag]
            tag_daterange[tag] = (timestamp, None)
            if prev_tag is not None:
                tag_daterange[prev_tag] = (prev_timestamp, timestamp)

        found = False
        for ticket in ticket_date:
            date = ticket_date[ticket]
            for tag in tag_daterange:
                date_range = tag_daterange[tag]
                if date_within(date, date_range) is True:
                    if tag in tag_tickets:
                        tag_tickets[tag].append(ticket)
                    else:
                        tag_tickets[tag] = [ticket]
                    found = True

        if not found:
            # Assign ticket to NOT_TAGGED group
            if NOT_TAGGED in tag_tickets:
                tag_tickets[NOT_TAGGED].append(ticket)
            else:
                tag_tickets[NOT_TAGGED] = [ticket]

        return tag_tickets

    def process(self, repository_name):
        """Query the GitHub API for the given repository
        and construct a mapping between git tags
        and JIRA tickets.

        Parameters
        ----------
        repository_name : `str`
            Name of the github repository.

        Returns
        -------
        changelog : `dict` (`str`: `dict`(`str`: `set` (`str`)))
            Maps a git tag to a ticket, and to a set of
            repositories that have been updated for that
            ticket.
        """
        url_pulls = f'{self.prefix_url}/{repository_name}/pulls?state=closed'
        url_tags = f'{self.prefix_url}/{repository_name}/tags'
        url_commits = f'{self.prefix_url}/{repository_name}/commits'
        sha_tickets = self.extractPulls(url_pulls)
        sha_tags = self.extractTags(url_tags)
        sha_commits = self.extractCommits(url_commits)
        return self.group_tickets(sha_tags, sha_tickets, sha_commits)


def date_within(date, date_range):
    """Determine whether the input timestamp
    is within the given range

    Parameters
    ----------
    date : `str`
        input date
    date_range : (`str`, `str`)
        date range
    """
    date_start, date_end = date_range

    datetime_start = str_timestamp(date_start)
    datetime = str_timestamp(date)
    if date_end is not None:
        datetime_end = str_timestamp(date_end)
        return datetime_start < datetime < datetime_end
    else:
        return datetime_start < datetime


def str_timestamp(timestamp):
    """Converts a timestamp to a datetime object

    Parameters
    ----------
    timestamp : `str`
        Input timestamp

    Returns
    -------
    date_time : `datetime`
        Corresponding datetime object
    """
    return strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")


def generate_changelog(repositories, mediator):
    """Query the GitHub API for the given repository
    and construct a mapping between git tags
    and JIRA tickets.

    Parameters
    ----------
    repositories : `list` [`str`]
        Names of the github repositories.
    mediator : `GitHubMediator`
        Mediates requests to GitHub API.

    Returns
    -------
    changelog : `dict` (`str`: `dict`(`str`: `set` (`str`)))
        Maps a git tag to a ticket, and to a set of
        repositories that have been updated for that
        ticket.
    """

    ticket_min_tag = {}
    changes_repo = {}

    for repo in repositories:
        changes = mediator.process(repo)
        changes_repo[repo] = changes
        for tag in changes:
            for ticket in changes[tag]:
                if (ticket not in ticket_min_tag or
                        tag_key(tag) < tag_key(ticket_min_tag[ticket])):
                    ticket_min_tag[ticket] = tag

    changelog = defaultdict(lambda: defaultdict(set))
    for repo in changes_repo:
        changes = changes_repo[repo]
        for tag in changes:
            for ticket in changes[tag]:
                min_tag = ticket_min_tag[ticket]
                changelog[min_tag][ticket].add(repo)
    return changelog


def get_ticket_summary(ticket):
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
    dbname = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "ticket.cache")
    db = dbm.open(dbname, "c")
    try:
        if ticket not in db:
            url = JIRA_API_URL + "/issue/" + ticket + "?fields=summary"
            logger.debug(f'JIRA URL = {url}')
            data = json.load(urlopen(url))
            db[ticket] = data['fields']['summary'].encode("UTF-8")
        # json gives us a unicode string, which we need to encode for storing
        # in the database, then decode again when we load it.
        return db[ticket].decode("UTF-8")
    except HTTPError:
        return ("Ticket description not available")
    finally:
        db.close()


def getGitHubAuth():
    """Get authentication tuple for GitHub
    Currently a hard-wired username, and an authentication token read from a
    file.

    Returns
    -------
    auth : `tuple` (`str`, `str`)
        Authentication tuple of user and token
    """
    with open(GITHUB_AUTH) as fd:
        return (GITHUB_USER[getpass.getuser()], fd.readline().strip())


def tag_key(tagname):
    """Converts a tagname ("m.n" or "m.n.p") into a key for sorting.

    Parameters
    ----------
    tagname : `str`
        name of release tag

    Returns
    -------
    sort_key : `int`
        numerical key for sorting.
    """
    return tuple(int(i) for i in tagname.split('.'))


def write_tag(writer, tagname, tickets):
    """Write ticket summaries for a given tag to output

    Parameters
    ----------
    writer : `TextIOBase`
        output writer
    tagname : `str`
        name of release tag
    tickets : `list` [`str`]
        list of ticket identifiers
    """
    if tagname == NOT_TAGGED:
        writer.write("<h2>Not tagged</h2>")
    else:
        writer.write(f"<h2>New in {hescape(tagname)}</h2>")
    writer.write("<ul>")
    for ticket in sorted(tickets):
        summary = get_ticket_summary(ticket)
        pkgs = ", ".join(sorted(tickets[ticket]))
        link_text = (f"<li><a href={JIRA_URL}/browse/"
                     f"{ticket}>{ticket}</a>: "
                     f"{hescape(summary)} [{hescape(pkgs)}]</li>")
        writer.write(link_text.format(ticket=ticket.upper(),
                     summary=summary, pkgs=pkgs))
    writer.write("</ul>")


def write_html(changelog, repositories, outfile):
    """Write changelog to file in HTML format

    Parameters
    ----------
    changelog : `dict` (`str`: `dict` (`str`: `set` (`str`)))
        mapping of tag to ticket identifiers.
    repositories: `list` [`str`]
        list of git repositories
    outfile: `str`
        the name of the output file
    """
    # FIXME: Needs a proper templating engine
    with open(outfile, 'w') as writer:
        writer.write("<html>")
        writer.write("<head><title>PFS Changelog</title></head>")
        writer.write("<body>")
        writer.write("<h1>PFS 2D DRP Changelog</h1>")

        # Always do the not-in-tag tickets first if they exist.
        if NOT_TAGGED in changelog:
            write_tag(writer, NOT_TAGGED, changelog.pop(NOT_TAGGED, None))

        # Then the other tags in order
        for tag in sorted(changelog, reverse=True, key=tag_key):
            write_tag(writer, tag, changelog[tag])

        gen_date = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M +00:00")
        repos = ", ".join(os.path.basename(r)
                          for r in sorted(repositories))
        writer.write(f"<p>Generated at {hescape(gen_date)} "
                     "by considering the following"
                     f" repositories: {hescape(repos)}.</p>")
        writer.write("</body>")
        writer.write("</html>")


def process(args):
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
    repo_regex = '^[A-Za-z0-9_]+$'
    repositories = [rr for rr in args.repositories if re.match(repo_regex, rr)]
    if set(repositories) != set(args.repositories):
        bad_repos = set(args.repositories) - set(repositories)
        logger.fatal(f'repositories "{bad_repos}"'
                     f' does not match format "{repo_regex}"".'
                     ' Exiting.')
        exit(1)

    # With GitHub API interations, authentication is most likely needed.
    # With no authentication (the default) only 60 requests to the github API
    # can be made per hour. See https://developer.github.com/v3/#rate-limiting
    auth_method = {'noauth': _noAuthentication,
                   'external': _externalAuthentication,
                   'internal': _internalAuthentication}
    auth = auth_method[args.authmethod](args.authfile)

    mediator = GitHubMediator(GITHUB_API_BASE_URL,
                              GITHUB_API_PARAMS,
                              auth,
                              GITHUB_API_MAX_PAGES)

    # Check whether for GitHub API calls, rate limit has been exceeded.
    # If so, cannot cannot continue.
    r = mediator.getRateLimit()
    remaining_requests = r['resources']['core']['remaining']
    logger.debug(f'There are {remaining_requests} '
                 'github API requests remaining.')
    if remaining_requests < 1:
        logger.fatal('Cannot access GitHub URL. Requests exceeded. Stopping')
        exit(1)

    # Finally, do the actual processing
    changelog = generate_changelog(repositories, mediator)
    write_html(changelog, repositories, args.outfile)
    logger.info('Processing COMPLETE. '
                f'Changelog written to file "{args.outfile}".')


def main():
    """Parse and process command-line arguments and generate the changelog
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('repositories', nargs='+',
                        help='list of repositories')
    parser.add_argument('--outfile', '-o', default='changelog.html',
                        help='name of output file')
    parser.add_argument("--authmethod", '-m', default='internal',
                        choices=['external', 'internal', 'noauth'],
                        help="Authentication method.")
    parser.add_argument('--authfile', '-a',
                        help='file providing GitHub API authentication')
    parser.add_argument("-L", "--loglevel",
                        choices=['trace', 'debug', 'info',
                                 'warn', 'error', 'fatal'],
                        help=("logging level"))

    args = parser.parse_args()
    process(args)
