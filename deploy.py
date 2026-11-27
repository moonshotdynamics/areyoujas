"""Ask Railway to deploy the current commit of the web service.

Railway does not auto-deploy this service on push, and serviceInstanceRedeploy
replays the commit the service was created with -- so the commit has to be named.
    RAILWAY_TOKEN=... python deploy.py
"""
import json, os, subprocess, urllib.request

API = "https://backboard.railway.com/graphql/v2"
WEB_SERVICE = "547ecf5e-a13a-45cf-a4bb-2c3e2dc3d974"
ENV = "93c81d74-8a81-4d92-afbb-f3b15880c0dd"
Q = ('mutation($s:String!,$e:String!,$c:String!){ serviceInstanceDeployV2('
     'serviceId:$s, environmentId:$e, commitSha:$c) }')

def main():
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    body = json.dumps({"query": Q, "variables": {"s": WEB_SERVICE, "e": ENV, "c": sha}}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Authorization": "Bearer " + os.environ["RAILWAY_TOKEN"],
        "Content-Type": "application/json", "User-Agent": "curl/8.5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read())
    if d.get("errors"):
        raise SystemExit("deploy failed: " + d["errors"][0]["message"])
    print(f"deploying {sha[:10]}: {d['data']['serviceInstanceDeployV2']}")

if __name__ == "__main__":
    main()
