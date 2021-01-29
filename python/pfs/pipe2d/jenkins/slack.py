import requests

SLACK_AUTH = "/home/pprice/.pfs/slack_api_token"
SLACK_URL = "https://slack.com/api/chat.postMessage"
SLACK_CHANNEL = "CAFPUKB7E"  # Channel ID for #drp-2d-travis


__all__ = ("getSlackToken", "postSlack")


def getSlackToken():
    """Get API token for Slack

    Returns
    -------
    token : `str`
        Slack authentication token.
    """
    with open(SLACK_AUTH) as fd:
        return fd.readline().strip()


def postSlack(text, disable=False):
    """Post a message to Slack

    Parameters
    ----------
    text : `str`
        Text of the message to post.
    disable : `bool`, optional
        Disable actually posting anything?

    Returns
    -------
    response : `requests.Response`
        Response from the server.
    """
    if disable:
        print(f"Disabled posting the following to Slack: {text}")
        return None
    data = dict(token=getSlackToken(), channel=SLACK_CHANNEL, text=text)
    return requests.post(url=SLACK_URL, data=data)
