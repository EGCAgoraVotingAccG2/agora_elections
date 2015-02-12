#!/bin/bash
# ./results.sh -t tally.tar.gz -c config.json -s

# fixes errors on non-ascii characters
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8
export LANGUAGE=en_US.UTF-8

AGORA_RESULTS=/tmp/agora-results
VENV=/root/.virtualenvs
source $VENV/agora-results/bin/activate
$AGORA_RESULTS/agora-results $*
