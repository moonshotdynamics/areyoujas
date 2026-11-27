#!/usr/bin/env bash
# Nightly refresh, runs on Railway (different egress to Property24 than the home IP).
# Crawl -> rebuild -> commit the data back -> Railway redeploys the web service with fresh numbers.
set -u
cd "$(dirname "$0")"

python scrape.py --deep=60 || echo "scrape: partial"   # --deep fetches street addresses: no address, no sold join
python galleries.py 40 || echo "galleries: partial"   # photo galleries, budgeted; aborts on 503 and resumes from cache
python sold.py   || echo "sold: partial"
python build.py  || exit 1

# ponytail: last-write-wins on data files; fine while one crawler exists,
# switch to a lock/queue if a second source service is added.
git config user.email "crawler@areyoujas"
git config user.name  "areyoujas crawler"
git add listings.json sold.json data.json sold_audit.csv labels.json
if git diff --cached --quiet; then
  echo "no data changes"
else
  git commit -qm "data: refresh $(date -u +%Y-%m-%d)"
  git push -q "https://x-access-token:${GITHUB_TOKEN}@github.com/moonshotdynamics/areyoujas.git" HEAD:main \
    && echo "pushed data"
  # Railway does not auto-deploy this service on push; deploy the new commit explicitly.
  python deploy.py || echo "deploy trigger failed"
fi
