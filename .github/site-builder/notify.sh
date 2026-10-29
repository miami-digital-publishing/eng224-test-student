#!/usr/bin/env bash
# Opens (or updates) one issue when the website can't be built, and closes
# it again once a build succeeds. GitHub emails the student about the issue,
# so they hear about problems without having to check the Actions tab.
set -uo pipefail

TITLE="Your website didn't update"
LABEL="website-build"

existing=$(gh issue list --state open --label "$LABEL" --json number --jq '.[0].number // empty' 2>/dev/null)

if [ "${BUILD_OUTCOME}" = "success" ]; then
  if [ -n "$existing" ]; then
    gh issue close "$existing" --comment "Fixed! Your website built successfully and is updating now. 🎉"
  fi
  exit 0
fi

body_file=$(mktemp)
{
  if [ -f _build/report.md ]; then
    cat _build/report.md
  else
    echo "The website builder stopped before it could write a report."
  fi
  echo
  echo "---"
  echo "This issue closes by itself the next time your website builds successfully."
  echo "Full build details: ${RUN_URL}"
} > "$body_file"

gh label create "$LABEL" --color d93f0b --description "Problems building the website" >/dev/null 2>&1 || true

if [ -n "$existing" ]; then
  gh issue edit "$existing" --body-file "$body_file"
  gh issue comment "$existing" --body "The website still didn't build after your latest commit. The problem list above has been updated."
else
  gh issue create --title "$TITLE" --label "$LABEL" --body-file "$body_file"
fi
