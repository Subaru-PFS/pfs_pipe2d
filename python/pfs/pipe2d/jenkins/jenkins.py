import requests

# Jenkins user/auth is hard-wired, since no-one else has a Jenkins account
JENKINS_USER = "pprice"
JENKINS_AUTH = "/home/pprice/.pfs/jenkins_api_token"


def getJenkinsAuth():
    """Get authentication tuple for Jenkins

    Currently a hard-wired username, and an authentication token read from a
    file.
    """
    with open(JENKINS_AUTH) as fd:
        return (JENKINS_USER, fd.readline().strip())


def triggerJenkins(url, token, **data):
    """Trigger a Jenkins run

    Parameters
    ----------
    url : `str`
        URL for the Jenkins run.
    token : `str`
        Jenkins job token (this is distinct from the authentication token).
    """
    data["token"] = token
    return requests.post(url=url, auth=getJenkinsAuth(), data=data)
