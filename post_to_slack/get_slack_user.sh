#!/bin/sh

GITLAB_URL=${GITLAB_URL:-https://gitlab.imtf-devops.com}
GITLAB_API_VERSION=${GITLAB_API_VERSION:-v4}
GITLAB_API_TOKEN=${GITLAB_API_TOKEN:-uZVaLKEDfUdraP3yc8Fz}
SLACK_API_TOKEN=${SLACK_API_TOKEN:-xoxp-610305227218-985379115988-1479623413043-0f2ac374537004f48b2a5e728073672b}

FULL_USER_NAME=

while getopts "u:" opt; do
    case $opt in
        u) FULL_USER_NAME="${OPTARG}";;
    esac
done 

if [ -z "${FULL_USER_NAME}" ]; then

    if [ $# -ne 2 ]; then
        echo "Usage: $(basename $0) <git_url> <commit_id>"
        exit 1
    fi

    GIT_URL=$1
    GIT_COMMIT_ID=$2

    GIT_PROJECT_ID=$(curl --header "PRIVATE-TOKEN: ${GITLAB_API_TOKEN}" --silent \
        "${GITLAB_URL}/api/${GITLAB_API_VERSION}/search?scope=projects&search=$(basename $GIT_URL | sed s/\.git//1)" \
        | jq ".[] | select(.ssh_url_to_repo==\"${GIT_URL}\") | .id")

    if [ -z "${GIT_PROJECT_ID}" ]; then
        echo "No such GIT repository has been found. Ensure that the git repo variable is correct"
        exit 2
    fi

    FULL_USER_NAME=$(curl --header "PRIVATE-TOKEN: ${GITLAB_API_TOKEN}" --silent \
        "${GITLAB_URL}/api/${GITLAB_API_VERSION}/projects/${GIT_PROJECT_ID}/repository/commits/${GIT_COMMIT_ID}" \
        | jq ".committer_name" | sed 's/"//g')

fi

if [ "${#FULL_USER_NAME}" -lt 5 ]; then
    CAPITAL_USER=$(echo "${FULL_USER_NAME}" | tr 'a-z' 'A-Z')
    FULL_USER_NAME=$(curl --header "PRIVATE-TOKEN: ${GITLAB_API_TOKEN}" --silent \
    "${GITLAB_URL}/api/${GITLAB_API_VERSION}/users?per_page=300" | jq ".[] | select(.username == \"${FULL_USER_NAME}\" or .username == \"${CAPITAL_USER}\") | .name" | sed 's/"//g')
fi

LDAPSEARCH=$(which ldapsearch 2> /dev/null)
if [ -n "${LDAPSEARCH}" ]; then
    GIT_COMMIT_USER=$(${LDAPSEARCH} -h 10.2.0.6 -D ldapAmazon@IMTF.LOCAL -w 'I9ecb9cc89a17cb27bbec7307cfd8531e!' -x -LLL -o nettimeout=1 -b OU=IMTF,DC=IMTF,DC=LOCAL "(cn=${FULL_USER_NAME})" givenName sn 2>/dev/null | tr '\n' ':' | sed 's/^.*sn: \([^:]*\):givenName: \([^:]*\):.*$/\2 \1/1')
fi
GIT_COMMIT_USER="\"${GIT_COMMIT_USER:-$FULL_USER_NAME}\""

if [ -z "${GIT_COMMIT_USER}" ]; then
    echo "No such commit has been found. Ensure that the commit_id or the user name variable are correct"
    exit 2
fi

SLACK_USER_ID=$(curl --header "Authorization: Bearer ${SLACK_API_TOKEN}" \
    --header "Content-Type: application/json" --silent \
    "https://slack.com/api/users.list" \
    | jq ".members[] | select(.profile.display_name==${GIT_COMMIT_USER} or .profile.display_name_normalized==${GIT_COMMIT_USER}) | .id" | tail -n 1 | sed 's/"//g')

if [ -n "${SLACK_USER_ID}" ]; then
    echo "@${SLACK_USER_ID}"
fi

exit 0
