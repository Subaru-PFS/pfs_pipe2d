#!/usr/bin/env python
import argparse

from pfs.pipe2d.jenkins.github import tagPackage
from pfs.pipe2d.jenkins.jenkins import triggerJenkins


JENKINS_URL = "https://jenkins.princeton.edu/job/Sumire/job/Prime%20Focus%20Spectrograph/job/release/buildWithParameters"  # noqa
JENKINS_TOKEN = "pfs_pipe2d"


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
    if "_" in tag:
        raise RuntimeError("No underscores are permitted in the tag name")
    if message is None:
        message = f"Tag {tag} on branch {branch}"
    tagPackage("Subaru-PFS/datamodel", tag, message, branch=branch)
    tagPackage("Subaru-PFS/pfs_utils", tag, message, branch=branch)
    tagPackage("Subaru-PFS/drp_pfs_data", tag, message, branch=branch)
    tagPackage("Subaru-PFS/obs_pfs", tag, message, branch=branch)
    tagPackage("Subaru-PFS/drp_stella_data", tag, message, branch=branch)
    tagPackage("Subaru-PFS/drp_stella", tag, message, branch=branch)
    tagPackage("Subaru-PFS/pfs_pipe2d", tag, message, branch=branch)
    response = triggerJenkins(JENKINS_URL, JENKINS_TOKEN, GIT_TAG=tag)
    print("Triggered Jenkins.", response.text)


def main():
    """Parse command-line and run"""
    parser = argparse.ArgumentParser(description="Tag and release the 2D pipeline")
    parser.add_argument("-b", "--branch", default="master", help="Branch to tag")
    parser.add_argument("-m", "--message", help="Tag message")
    parser.add_argument("tag", help="Tag name to apply (no underscores)")
    args = parser.parse_args()
    run(args.tag, args.branch, args.message)


if __name__ == "__main__":
    main()
