import os
import urllib.request
import json
from pathlib import Path

TOKEN = os.environ["TRAFFIC_TOKEN"]
REPOSITORY = os.environ["GITHUB_REPOSITORY"]

HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {TOKEN}",
    "X-GitHub-Api-Version": "2026-03-10",
    "User-Agent": "github-traffic-graph",
}


def get_github_data(url):
    request = urllib.request.Request(url, headers=HEADERS)

    with urllib.request.urlopen(request) as response:
        return json.load(response)


views_data = get_github_data(
    f"https://api.github.com/repos/{REPOSITORY}/traffic/views?per=day"
)

clones_data = get_github_data(
    f"https://api.github.com/repos/{REPOSITORY}/traffic/clones?per=day"
)

total_views = views_data["count"]
unique_visitors = views_data["uniques"]

total_clones = clones_data["count"]
unique_cloners = clones_data["uniques"]

svg = f"""
<svg
    xmlns="http://www.w3.org/2000/svg"
    width="700"
    height="180"
    viewBox="0 0 700 180"
>

<rect
    width="100%"
    height="100%"
    rx="10"
    fill="#0d1117"
/>

<text
    x="30"
    y="40"
    font-family="sans-serif"
    font-size="20"
    font-weight="bold"
    fill="#c9d1d9"
>
    GitHub Repository Traffic
</text>

<text
    x="30"
    y="85"
    font-family="sans-serif"
    font-size="17"
    fill="#8b949e"
>
    👀 {total_views} views · {unique_visitors} unique visitors
</text>

<text
    x="30"
    y="125"
    font-family="sans-serif"
    font-size="17"
    fill="#8b949e"
>
    📦 {total_clones} clones · {unique_cloners} unique cloners
</text>

</svg>
"""

Path("traffic.svg").write_text(svg)

print(
    f"Generated traffic.svg: "
    f"{total_views} views, "
    f"{unique_visitors} unique visitors, "
    f"{total_clones} clones, "
    f"{unique_cloners} unique cloners"
)