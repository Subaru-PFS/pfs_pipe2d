#!/usr/bin/env python
import os
import json
import getpass
import argparse
import requests
import datetime

JENKINS_URL = "https://jenkins.princeton.edu/job/Sumire/job/Prime%20Focus%20Spectrograph/job/release/buildWithParameters"  # noqa
JENKINS_TOKEN = "pfs_pipe2d"
# Jenkins user/auth can be hard-wired, since no-one else has a Jenkins account
JENKINS_USER = "pprice"
JENKINS_AUTH = "/home/pprice/.pfs/jenkins_api_token"

# Github users are hard-coded, because there's only a limited number of us with access to the
# Princeton clusters where this script can be successfully used (because Jenkins is behind a firewall).
GITHUB_URL = "https://api.github.com/repos"
GITHUB_USER = {"pprice": "PaulPrice",
               "hassans": "hassanxp",
               "rhl": "RobertLuptonTheGood",
               "ncaplar": "nevencaplar",
               "craigl": "CraigLoomis",
               }
GITHUB_AUTH = os.path.join(os.environ["HOME"], ".pfs", "github_api_token")
USER_NAME = {"pprice": "Paul Price",
             "hassans": "Hassan Siddiqui",
             "ncaplar": "Neven Caplar",
             "rhl": "Robert Lupton the Good",
             "craigl": "Craig Loomis",
             }
USER_EMAIL = {"pprice": "price@astro.princeton.edu",
              "hassans": "hassans@astro.princeton.edu",
              "ncaplar": "ncaplar@princeton.edu",
              "rhl": "rhl@astro.princeton.edu",
              "craigl": "cloomis@astro.princeton.edu",
              }


def getJenkinsAuth():
    """Get authentication tuple for Jenkins

    Currently a hard-wired username, and an authentication token read from a
    file.
    """
    with open(JENKINS_AUTH) as fd:
        return (JENKINS_USER, fd.readline().strip())


def getGitHubAuth():
    """Get authentication tuple for GitHub

    Currently a hard-wired username, and an authentication token read from a
    file.
    """
    with open(GITHUB_AUTH) as fd:
        return (GITHUB_USER[getpass.getuser()], fd.readline().strip())


def triggerJenkins(tag):
    """Trigger the Jenkins build

    Parameters
    ----------
    tag : `str`
        Tag name to apply.
    version : `str`
        Version name to use.
    """
    response = requests.post(url=JENKINS_URL, auth=getJenkinsAuth(),
                             data=dict(GIT_TAG=tag, token=JENKINS_TOKEN))
    print("Triggered Jenkins.", response.text)
    return response


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


def getTagger():
    """Generate the information about who is doing the tagging.

    We determine the name and email address from the username.

    Returns
    -------
    name : `str`
        Name of the tagger.
    email : `str`
        Email of the tagger.
    date : `str`
        ISO-8601 date.
    """
    user = getpass.getuser()
    if user not in USER_NAME or user not in USER_EMAIL:
        raise RuntimeError(f"Unrecognised username: {user}")
    return dict(name=USER_NAME[user], email=USER_EMAIL[user],
                date=datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z")


def tagPackage(package, tag, message, branch="master"):
    """Tag the package in GitHub

    Parameters
    ----------
    package : `str`
        Package name (of the form "User/Package").
    tag : `str`
        Tag name to apply.
    message : `str`
        Message for annotated tag.
    branch : `str`
        Branch to tag.
    """
    # First, get the SHA for the branch
    auth = getGitHubAuth()
    try:
        targetSha = getSha(package, branch, auth)
    except Exception as exc:
        if branch == "master":
            raise RuntimeError(f"Unable to determine SHA of master for {package}") from exc
        targetSha = getSha(package, "master", auth)

    # Create an annotation on the branch
    response = requests.post(url=f"{GITHUB_URL}/{package}/git/tags", auth=auth,
                             data=json.dumps(dict(tag=tag, message=message, object=targetSha,
                                                  type="commit", tagger=getTagger())))
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


def run(tag, branch="master", message=None):
    """Tag all packages and run Jenkins to create the release

    Parameters
    ----------
    tag : `str`
        Tag name to apply.
    branch : `str`, optional
        Branch to tag.
    message : `str`, optional
        Message for annotated tag.
    """
    if message is None:
        message = f"Tag {tag} on branch {branch}"
    tagPackage("Subaru-PFS/datamodel", tag, message, branch=branch)
    tagPackage("Subaru-PFS/pfs_utils", tag, message, branch=branch)
    tagPackage("Subaru-PFS/drp_pfs_data", tag, message, branch=branch)
    tagPackage("Subaru-PFS/obs_pfs", tag, message, branch=branch)
    tagPackage("Subaru-PFS/drp_stella_data", tag, message, branch=branch)
    tagPackage("Subaru-PFS/drp_stella", tag, message, branch=branch)
    tagPackage("Subaru-PFS/pfs_pipe2d", tag, message, branch=branch)
    triggerJenkins(tag)


def main():
    """Parse command-line and run"""
    parser = argparse.ArgumentParser(description="Tag and release the 2D pipeline")
    parser.add_argument("-b", "--branch", default="master", help="Branch to tag")
    parser.add_argument("-m", "--message", help="Tag message")
    parser.add_argument("tag", help="Tag name to apply")
    args = parser.parse_args()
    run(args.tag, args.branch, args.message)


if __name__ == "__main__":
    main()
