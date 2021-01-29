#!/usr/bin/env python
import getpass
import argparse

from pfs.pipe2d.jenkins.jenkins import triggerJenkins


JENKINS_URL = "https://jenkins.princeton.edu/job/Sumire/job/Prime%20Focus%20Spectrograph/job/integrationTest/buildWithParameters"  # noqa
JENKINS_TOKEN = "integrationTest"


def run(tag, branch="master"):
    """Run the integration test with Jenkins
    Parameters
    ----------
    branch : `str`, optional
        Branch to test.
    """
    response = triggerJenkins(JENKINS_URL, JENKINS_TOKEN, BRANCH=tag, USERNAME=getpass.getuser())
    print("Triggered integration test.", response.text)


def main():
    """Parse command-line and run"""
    parser = argparse.ArgumentParser(description="Trigger an integration test on Jenkins")
    parser.add_argument("branch", help="Branch to test")
    args = parser.parse_args()
    run(args.branch)


if __name__ == "__main__":
    main()
