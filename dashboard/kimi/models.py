import os, json, urllib.request
req = urllib.request.Request("https://api.moonshot.ai/v1/models", headers={"Authorization": "Bearer " + os.environ["SECRET_VALUE"]})
d = json.load(urllib.request.urlopen(req, timeout=30))
print("\n".join(sorted(m["id"] for m in d.get("data", []))) if "data" in d else print(d))
