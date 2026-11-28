"""Kick the crawler service on Railway: it runs refresh.sh (sold -> scrape -> galleries -> build -> deploy)
from Railway's egress IP, which Property24 has not throttled. Same call the 03:00 cron makes."""
import json, os, subprocess, urllib.request

API = "https://backboard.railway.com/graphql/v2"
CRAWLER = "13c3bccb-0f80-4959-ad15-8186e33eaea2"
ENV = "93c81d74-8a81-4d92-afbb-f3b15880c0dd"
Q = ('mutation($s:String!,$e:String!,$c:String!){ serviceInstanceDeployV2('
     'serviceId:$s, environmentId:$e, commitSha:$c) }')

sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd="/data/projects/areyoujas", text=True).strip()
body = json.dumps({"query": Q, "variables": {"s": CRAWLER, "e": ENV, "c": sha}}).encode()
req = urllib.request.Request(API, data=body, headers={
    "Authorization": "Bearer " + os.environ["RAILWAY_TOKEN"],
    "Content-Type": "application/json", "User-Agent": "curl/8.5.0"})
with urllib.request.urlopen(req, timeout=60) as r:
    d = json.loads(r.read())
print("errors:", d.get("errors"))
print("crawler deployment:", (d.get("data") or {}).get("serviceInstanceDeployV2"))
