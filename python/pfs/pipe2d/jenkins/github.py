import os
import json
import requests
import datetime

from .users import UserDatabase, getUser

__all__ = ("getGithubAuth", "getSha")

GITHUB_URL = "https://api.github.com/repos"
GITHUB_AUTH = os.path.join(os.environ["HOME"], ".pfs", "github_api_token")


def getGithubAuth():
    """Get authentication tuple for GitHub

    The authentication token is read from ``~/.pfs/github_api_token``.

    Returns
    -------
    name : `str`
        GitHub user name.s
    token : `str`
        GitHub authentication token.
    """
    users = UserDatabase.create()
    with open(GITHUB_AUTH) as fd:
        return (users.myGitHub, fd.readline().strip())


def getSha(package, branch, auth):
    """Get SHA of package from GitHub

    Parameters
    ----------
    package : `str`
        Package name (of the form "User/Package").
    branch : `str`
        Branch of interest.
    auth : `tuple` (`str`, `str`)
        Authentication tuple for GitHub.

    Returns
    -------
    sha : `str`
        SHA of package.
    """
    response = requests.get(url=f"{GITHUB_URL}/{package}/git/ref/heads/{branch}", auth=auth)
    if response.status_code != 200:
        raise RuntimeError(f"Failed to get SHA for {package}@{branch}: {response.text}")
    return response.json()["object"]["sha"]


def tagPackage(package, tag, message, branch="master", name=None, email=None, date=None):
    """Tag the package in GitHub

    This involves identifying the SHA for the head of the branch, creatine an
    annotation on that SHA, and then tagging the annotation.

    Parameters
    ----------
    package : `str`
        Package name (of the form "User/Package").
    tag : `str`
        Tag name to apply.
    message : `str`
        Message for annotated tag.
    branch : `str`, optional
        Branch to tag.
    name : `str`, optional
        Name of the person creating the tag.
    email : `str`, optional
        E-mail address of the person creating the tag.
    date : `str`, optional
        ISO-8601 date+time of the tag.

    Returns
    -------
    response : `requests.Response`
        Response from the server for the final request.
    """
    tagger = dict(
        name=name if name is not None else getUser().name,
        email=email if email is not None else getUser().email,
        date=date if date is not None else datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
    )

    # First, get the SHA for the branch
    auth = getGithubAuth()
    try:
        targetSha = getSha(package, branch, auth)
    except Exception as exc:
        if branch == "master":
            raise RuntimeError(f"Unable to determine SHA of master for {package}") from exc
        targetSha = getSha(package, "master", auth)

    # Create an annotation on the branch
    response = requests.post(url=f"{GITHUB_URL}/{package}/git/tags", auth=auth,
                             data=json.dumps(dict(tag=tag, message=message, object=targetSha,
                                                  type="commit", tagger=tagger)))
    if response.status_code != 201:
        raise RuntimeError(f"Failed to create tag annotation on {package}@{targetSha}: {response.text}")
    tagSha = response.json()["sha"]

    # Put a tag on the annotation
    response = requests.post(url=f"{GITHUB_URL}/{package}/git/refs", auth=auth,
                             data=json.dumps(dict(sha=tagSha, ref=f"refs/tags/{tag}")))
    if response.status_code != 201:
        raise RuntimeError(f"Failed to tag {package}@{tagSha}: {response.text}")
    print(f"Tagged {package}@{branch}({targetSha})={tag}")
    return response
