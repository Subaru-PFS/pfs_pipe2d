#!/bin/bash

WORKDIR=/scratch/pprice/jenkins
STACK=/scratch/price/jenkins/stack
HERE=$(pwd)

set -ev

# What's the tag to build?
echo --------------------------------
echo HOSTNAME=$HOSTNAME
echo HOME=$HOME
echo USER=$USER
echo TERM=$TERM
echo CHANGE_ID=$CHANGE_ID
echo CHANGE_TARGET=$CHANGE_TARGET
echo WORKSPACE=$WORKSPACE
echo JENKINS_HOME=$JENKINS_HOME
echo HERE=$HERE
echo EUPS_PATH=$EUPS_PATH
echo GIT_BRANCH=$GIT_BRANCH
echo GIT_LOCAL_BRANCH=$GIT_LOCAL_BRANCH
echo GIT_COMMIT=$GIT_COMMIT
echo BRANCH_NAME=$BRANCH_NAME
echo --------------------------------
env
echo --------------------------------
unsetup eups
. $STACK/loadLSST.bash
env
echo --------------------------------
#cd $WORKDIR
#$HERE/bin/