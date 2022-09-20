from collections import defaultdict
import json
import os
import re
from urllib.error import HTTPError
import requests
import dbm
import argparse
import lsst.log
from configparser import ConfigParser
from html import escape as hescape
import getpass
import datetime

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

TAG_REGEX = r"^w\.(\d{4})\.(\d{2})$"
"""Git tag regular expression (`str`).
The format of a tag. In the above case, for weeklies eg w.2022.17 .
"""

NOT_TAGGED = 'NOT-TAGGED'
"""Label for tickets not assigned to a tag (`str`).
For grouping recently closed tickets that are not in a release, so not tagged.
"""

DATE_TOL_MIN = 2
"""The tolerance for comparing ticket timestamps against tag ranges [minutes]
"""

REPO_PRINCIPAL = 'pfs_pipe2d'
"""Name of repo that provides tag-date information
"""


def _no_authentication(authfile):
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


def _external_authentication(authfile):
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


def _internal_authentication(authfile):
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
    return get_github_auth()


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

    def _get_request(self, url):
        """Retrieves HTTP request
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
            r = self._get_request(url)
            yield json.loads(r.text)
            if 'next' in r.links:
                url = r.links['next']['url']
            else:
                return

    def retrieve_request_as_dict(self, url):
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
        return self._get_request(url).json()


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

    def get_rate_limit(self):
        """Returns the rate limit (number of requests per hour)
        to the GitHub API server.
        """
        result = self.paginator.retrieve_request_as_dict(RATE_LIMIT_URL)
        return result

    def extract_pulls(self, url):
        """Retrieves details of each pull request, returning
        those that have ticket information.

        Up to but excluding tag w.2020.20, 2D DRP repositories
        were not tagged consistently. So instead of
        relating tickets to shas (and relate those shas to tags)
        need to rely on datestamps on each ticket,
        and relate that information to
        tag date ranges provided by
        the 'principal' repoository (usually pfs_pipe2d).

        Parameters
        ----------
        url : `str`
            The URL endpoint for pull requests.

        Returns
        -------
        ticket_date : `dict` (`str`: `str`)
            mapping of ticket ID to date
        """
        ticket_date = {}
        pages = self.paginator.pages(url)
        for page in pages:
            for entry in page:
                label = entry['head']['label']
                timestamp = entry['merged_at']
                if timestamp is None:
                    # Pull request had been rejected - ignore
                    continue
                m = re.search(GITHUB_API_TICKET_REGEX, label)
                if m is not None:
                    ticket = m.group(1)
                    ticket_date[ticket] = timestamp
        return ticket_date

    def extract_tags(self, url):
        """Retrieves details of each git tag

        Parameters
        ----------
        url : `str`
            The URL endpoint for requesting tag information.

        Returns
        -------
        tag_commit : `dict` (`str`: `str`)
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

    def extract_commits(self, url):
        """Retrieves merged commits

        Parameters
        ----------
        url : `str`
            The URL endpoint for requesting tag information.

        Returns
        -------
        commit_date : `dict` (`str`: `str`)
            Mapping of commit sha to timestamp
        """
        commit_date = {}
        pages = self.paginator.pages(url)
        for page in pages:
            for entry in page:
                sha = entry['sha']
                timestamp = entry['commit']['committer']['date']
                commit_date[sha] = timestamp
        return commit_date

    def tag_to_date(self, tag_commit, commit_date):
        """Associates a tag to its timestamp

        Parameters
        ----------
        tag_commit : `dict` (`str`: `str`)
            mapping of tag to commit sha
        commit_date : `dict` (`str`: `str`)
            mapping of commit sha to timestamp

        Returns
        -------
        tag_date : `dict` (`str`: str`)
            mapping of tag to timestamp
        """
        tag_date = {}
        for tag in tag_commit:
            commit = tag_commit[tag]
            if commit in commit_date:
                tag_date[tag] = commit_date[commit]
            else:
                logger.debug(f'Cannot find commit information for tag {tag}. '
                             'Was tag made on a different branch to master?')
        return tag_date

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
        tag_date : `dict` (`str`: `str`)
            Mapping from tag to date
        ticket_date : `dict` (`str`: `str`)
            Mapping from ticket to date
        """
        url_pulls = f'{self.prefix_url}/{repository_name}/pulls?state=closed'
        url_tags = f'{self.prefix_url}/{repository_name}/tags'
        url_commits = f'{self.prefix_url}/{repository_name}/commits'

        ticket_date = self.extract_pulls(url_pulls)

        tag_commit = self.extract_tags(url_tags)
        commit_date = self.extract_commits(url_commits)
        tag_date = self.tag_to_date(tag_commit, commit_date)

        return tag_date, ticket_date


def tag_to_tickets(tag_date, ticket_date):
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
    tag_tickets : `dict` (`str`: `set` [`str`])
        mapping of tag to corresponding tickets
    """
    tag_tickets = defaultdict(set)
    tag_daterange = {}
    prev_timestamp = None
    prev_tag = None
    for tag, timestamp in tag_date.items():
        tag_daterange[tag] = (None, timestamp)
        if prev_tag is not None:
            tag_daterange[prev_tag] = (timestamp, prev_timestamp)
        prev_tag = tag
        prev_timestamp = timestamp
    found = False
    for ticket, date in ticket_date.items():

        assert date is not None,  "date is None which should have been filtered out."
        for tag, date_range in tag_daterange.items():
            if date_within(date, date_range):
                tag_tickets[tag].add(ticket)
                found = True
        if not found:
            tag_tickets[NOT_TAGGED].add(ticket)
    return tag_tickets


def date_within(date, date_range):
    """Determine whether the input timestamp
    is within the given range

    Parameters
    ----------
    date : `str`
        input date
    date_range : (`str`, `str`)
        date range

    Returns
    -------
    is_within    : `bool`
        True if input date is within range
    """
    date_start, date_end = date_range

    dt_end = str_timestamp(date_end)

    # ticket date can be just a little outside
    # of tag date, by less than DATE_TOL_MIN minutes
    dt_target = str_timestamp(date) - datetime.timedelta(minutes=DATE_TOL_MIN)
    if date_start is not None:
        dt_start = str_timestamp(date_start)
        return dt_start <= dt_target < dt_end
    else:
        return dt_target < dt_end


def str_timestamp(timestamp):
    """Converts a timestamp to a datetime object

    Parameters
    ----------
    timestamp : `str`
        Input timestamp

    Returns
    -------
    date_time : `datetime.datetime`
        Corresponding datetime object
    """
    return datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")


def generate_changelog(repositories, mediator):
    """Query the GitHub API for the given repository
    and construct a mapping between git tags
    and JIRA tickets.

    Parameters
    ----------
    repositories : `set` [`str`]
        Names of the github repositories.
    mediator : `GitHubMediator`
        Mediates requests to GitHub API.

    Returns
    -------
    changelog : `dict` (`str`: `dict`(`str`: `set` [`str`]))
        Maps a git tag to a ticket, and to a set of
        repositories that have been updated for that
        ticket.
    """
    changelog = {}

    # Generate tag-date mapping based using
    # principal repository only.
    tag_date_principal = {}

    # This should already be checked when parsing arguments
    assert REPO_PRINCIPAL in repositories

    tag_date_principal, ticket_date = mediator.process(REPO_PRINCIPAL)

    changelog = {tag: defaultdict(set) for tag in tag_date_principal}
    changelog[NOT_TAGGED] = defaultdict(set)

    populate_changelog(changelog, REPO_PRINCIPAL,
                       tag_date_principal, ticket_date)

    repositories.remove(REPO_PRINCIPAL)

    for repo in repositories:
        # Ignore tag_date information from these repos
        # As we are using the one from the principal repo
        _, ticket_date = mediator.process(repo)
        populate_changelog(changelog, repo, tag_date_principal, ticket_date)

    return changelog


def populate_changelog(changelog, repo, tag_date, ticket_date):
    """Populates the changelog with tickets closed
    in this repository.

    Parameters
    ----------
    changelog : `dict` (`str`: `dict`(`str`: `set` [`str`]))
        Maps a git tag to a ticket, and to a set of
        repositories that have been updated for that
        ticket.
    repo : `str`
        Name of the github repository.
    tag_date : `dict` (`str`: `str`)
        mapping of tag to date
    ticket_date : `dict` (`str`: `str`)
        mapping of ticket to date
    """
    tag_tickets = tag_to_tickets(tag_date, ticket_date)
    for tag, tickets in tag_tickets.items():
        for ticket in tickets:
            changelog[tag][ticket].add(repo)


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
            url = f'{JIRA_API_URL}/issue/{ticket}?fields=summary'
            logger.debug(f'JIRA URL = {url}')
            data = requests.get(url).json()
            db[ticket] = data['fields']['summary'].encode("UTF-8")
        # json gives us a unicode string, which we need to encode for storing
        # in the database, then decode again when we load it.
        return db[ticket].decode("UTF-8")
    except HTTPError:
        return ("Ticket description not available")
    finally:
        db.close()


def get_github_auth():
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
    if not tickets:
        writer.write("<li><i>None</i></li>")
    else:
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
    changelog : `dict` (`str`: `dict` (`str`: `set` [`str`]))
        mapping of tag to ticket identifiers.
    repositories: `set` [`str`]
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
        log_level = getattr(lsst.log.Log, args.loglevel.upper())
        logger.setLevel(log_level)

    # Check that repository names are valid
    repo_regex = '^[A-Za-z0-9_]+$'
    repositories = {rr for rr in args.repositories if re.match(repo_regex, rr)}
    if set(repositories) != set(args.repositories):
        bad_repos = set(args.repositories) - set(repositories)
        logger.fatal(f'repositories "{bad_repos}"'
                     f' does not match format "{repo_regex}"".'
                     ' Exiting.')
        exit(1)

    # Need to have the 'principal repository', usually pfs_utils,
    # in the repository list, otherwise for tags up to w.2020.20
    # cannot associate tickets to tags.
    if REPO_PRINCIPAL not in repositories:
        logger.fatal(f'Repository {REPO_PRINCIPAL} is not in input list. '
                     'Need this to determine ticket to tag assignment.')
        exit(1)

    # With GitHub API interations, authentication is most likely needed.
    # With no authentication (the default) only 60 requests to the github API
    # can be made per hour. See https://developer.github.com/v3/#rate-limiting
    auth_method = {'noauth': _no_authentication,
                   'external': _external_authentication,
                   'internal': _internal_authentication}
    auth = auth_method[args.authmethod](args.authfile)

    mediator = GitHubMediator(GITHUB_API_BASE_URL,
                              GITHUB_API_PARAMS,
                              auth,
                              GITHUB_API_MAX_PAGES)

    # Check whether for GitHub API calls, rate limit has been exceeded.
    # If so, cannot continue.
    r = mediator.get_rate_limit()
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
                        help=('list of repositories. '
                              'This needs to contain pfs_utils '
                              'to determine tag-ticket assignment.'))
    parser.add_argument('--outfile', '-o', default='changelog.html',
                        help='name of output file')
    parser.add_argument("--authmethod", '-m', default='internal',
                        choices=['external', 'internal', 'noauth'],
                        help="Authentication method.")
    parser.add_argument('--authfile', '-a',
                        help='file providing GitHub API authentication')
    parser.add_argument("--loglevel", "-L",
                        choices=['trace', 'debug', 'info',
                                 'warn', 'error', 'fatal'],
                        help=("logging level"))

    args = parser.parse_args()
    process(args)
