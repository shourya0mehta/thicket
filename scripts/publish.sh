#!/usr/bin/env bash
# Publish this repository to GitHub and switch on the static demo.
#
#   ./scripts/publish.sh                 # public repo named "thicket" under your account
#   ./scripts/publish.sh my-name private # custom name and visibility
#
# Needs the GitHub CLI, logged in once with: gh auth login
# Afterwards, optionally build the frog and insect dataset and train the head:
#   gh workflow run dataset-inat.yml     (about 1.5 to 3 hours on GitHub's runners)
set -euo pipefail

NAME="${1:-thicket}"
VISIBILITY="${2:-public}"
DESCRIPTION="Turn field recordings into transparent biodiversity evidence: BirdNET detections, events, metrics, QC and exports."

command -v gh >/dev/null || { echo "Install the GitHub CLI first: https://cli.github.com"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "Run 'gh auth login' first."; exit 1; }
cd "$(git rev-parse --show-toplevel)"

OWNER="$(gh api user -q .login)"
if gh repo view "$OWNER/$NAME" >/dev/null 2>&1; then
  echo "Repo $OWNER/$NAME exists; pushing to it."
  git remote get-url origin >/dev/null 2>&1 || git remote add origin "https://github.com/$OWNER/$NAME.git"
  git push -u origin main
else
  gh repo create "$OWNER/$NAME" "--$VISIBILITY" --description "$DESCRIPTION" --source . --remote origin --push
fi

gh repo edit "$OWNER/$NAME" --add-topic bioacoustics --add-topic biodiversity --add-topic birdnet \
  --add-topic fastapi --add-topic react --homepage "https://$OWNER.github.io/$NAME/" >/dev/null || true

if [ "$VISIBILITY" = "public" ]; then
  # GitHub Pages from Actions, then build the demo.
  gh api -X POST "repos/$OWNER/$NAME/pages" -f build_type=workflow >/dev/null 2>&1 || true
  gh workflow run pages.yml --repo "$OWNER/$NAME" || true
  echo "Demo will be live at https://$OWNER.github.io/$NAME/ in a few minutes."
fi
echo "Done: https://github.com/$OWNER/$NAME"
