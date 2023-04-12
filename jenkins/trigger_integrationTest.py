#!/usr/bin/env python
import getpass
import argparse
import logging

from pfs.pipe2d.jenkins.jenkins import triggerJenkins


JENKINS_URL = "https://jenkins.princeton.edu/job/Sumire/job/Prime%20Focus%20Spectrograph/job/integrationTest/buildWithParameters"  # noqa
JENKINS_TOKEN = "integrationTest"


def run(commit):
    """Run the integration test with Jenkins
    Parameters
    ----------
    commit : `str`, optional
        Branch/tag commit to test.
    """

    logging.basicConfig()
    logging.getLogger().setLevel(logging.DEBUG)
    requests_log = logging.getLogger("requests.packages.urllib3")
    requests_log.setLevel(logging.DEBUG)
    requests_log.propagate = True

    response = triggerJenkins(JENKINS_URL, JENKINS_TOKEN, BRANCH=commit, USERNAME=getpass.getuser())
    print("Triggered integration test.", response.text)
    print(response.request.url)
    print(response.request.headers)
    print(response.request.data)


def main():
    """Parse command-line and run"""
    parser = argparse.ArgumentParser(description="Trigger an integration test on Jenkins")
    parser.add_argument("branch", help="Branch to test")
    args = parser.parse_args()
    run(args.branch)


if __name__ == "__main__":
    main()
