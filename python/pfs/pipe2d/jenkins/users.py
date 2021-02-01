import getpass
from types import SimpleNamespace

__all__ = ("User", "UserDatabase", "getUser")


class User(SimpleNamespace):
    """Details about a PFS user

    Parameters
    ----------
    userName : `str`
        User name on the Princeton cluster.
    name : `str`
        Name of the user.
    gitHub : `str`
        GitHub user name.
    slack : `str`
        Slack user name.
    email : `str`
        E-mail address.
    """
    def __init__(self, userName, name, gitHub, slack, email):
        super().__init__(userName=userName, name=name, gitHub=gitHub, slack=slack, email=email)


class UserDatabase:
    def __init__(self):
        """Ctor"""
        self._users = {}
        self.myUserName = getpass.getuser()

    @classmethod
    def create(cls):
        """Create a populated `UserDatabase`

        Users are hard-coded, because there's only a limited number of us with
        access to the Princeton clusters where this script can be successfully
        used (because Jenkins is behind a firewall).

        We could cache the result, effectively making this a singleton, but
        it's relatively cheap to create.
        """
        self = cls()
        self.add("pprice", "Paul Price", "PaulPrice", "U3A1VCXQT", "price@astro.princeton.edu")
        self.add("hassans", "Hassan Siddiqui", "hassanxp", "UA82J1WP3", "hassans@astro.princeton.edu")
        self.add("ncaplar", "Neven Caplar", "nevencaplar", "U6YEJEW8L", "ncaplar@princeton.edu")
        self.add("rhl", "Robert Lupton the Good", "RobertLuptonTheGood", "U39GV64AU",
                 "rhl@astro.princeton.edu")
        self.add("craigl", "Craig Loomis", "craigl", "U3A2P4FEH", "cloomis@astro.princeton.edu")
        return self

    def add(self, userName, name, gitHub, slack, email):
        """Add a user

        Parameters
        ----------
        userName : `str`
            User name on the Princeton cluster.
        name : `str`
            Name of the user.
        gitHub : `str`
            GitHub user name.
        slack : `str`
            Slack user name.
        email : `str`
            E-mail address.
        """
        self._users[userName] = User(userName, name, gitHub, slack, email)

    def __getitem__(self, userName):
        """Retrieve details by user name"""
        return self._users[userName]

    def myName(self):
        """Retrieve name of the current user"""
        return self.me.name

    def myGitHub(self):
        """Retrieve GitHub user name of the current user"""
        return self.me.gitHub

    def mySlack(self):
        """Retrieve Slack user name of the current user"""
        return self.me.slack

    def myEmail(self):
        """Retrieve e-mail address of the current user"""
        return self.me.email

    @property
    def me(self):
        if self.myUserName not in self._users:
            RuntimeError(f"Unrecognised username: {self.myUserName}")
        return self._users[self.myUserName]


def getUser(userName=None):
    """Retrieve details for a user

    Parameters
    ----------
    userName : `str`, optional
        User name for which to retrieve details. Defaults to the current user.

    Returns
    --------
    user : `User`
        User details.
    """
    users = UserDatabase.create()
    return users[userName] if userName is not None else users.me
