import os
import urllib.request
import json
from pathlib import Path

TOKEN = os.environ["TRAFFIC_TOKEN"]
REPOSITORY = os.environ["GITHUB_REPOSITORY"]

url = f"https://api.github.com/repos/{REPOSITORY}/traffic/views?per=day"

request = urllib.request.Request(
    url,
    headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {TOKEN}",
        "X-GitHub-Api-Version": "2026-03-10",
        "User-Agent": "github-traffic-graph",
    },
)

with urllib.request.urlopen(request) as response:
    data = json.load(response)

views = data["views"]

WIDTH = 800
HEIGHT = 300

LEFT = 60
RIGHT = 30
TOP = 50
BOTTOM = 60

GRAPH_WIDTH = WIDTH - LEFT - RIGHT
GRAPH_HEIGHT = HEIGHT - TOP - BOTTOM

max_value = max(
    [entry["count"] for entry in views]
    + [entry["uniques"] for entry in views]
    + [1]
)

def x_position(index):
    if len(views) <= 1:
        return LEFT

    return LEFT + (index / (len(views) - 1)) * GRAPH_WIDTH

def y_position(value):
    return TOP + GRAPH_HEIGHT - (value / max_value) * GRAPH_HEIGHT

view_points = " ".join(
    f"{x_position(i):.1f},{y_position(entry['count']):.1f}"
    for i, entry in enumerate(views)
)

unique_points = " ".join(
    f"{x_position(i):.1f},{y_position(entry['uniques']):.1f}"
    for i, entry in enumerate(views)
)

total_views = data["count"]
unique_visitors = data["uniques"]

date_labels = ""

for i, entry in enumerate(views):
    if i % 2 == 0 or i == len(views) - 1:
        date = entry["timestamp"][5:10]

        date_labels += f"""
        <text
            x="{x_position(i):.1f}"
            y="{HEIGHT - 25}"
            font-size="11"
            text-anchor="middle"
            fill="#8b949e"
        >
            {date}
        </text>
        """

svg = f"""
<svg
    xmlns="http://www.w3.org/2000/svg"
    width="{WIDTH}"
    height="{HEIGHT}"
    viewBox="0 0 {WIDTH} {HEIGHT}"
>

<style>
    .title {{
        font: bold 18px sans-serif;
        fill: #c9d1d9;
    }}

    .stat {{
        font: 14px sans-serif;
        fill: #8b949e;
    }}

    .axis {{
        stroke: #30363d;
        stroke-width: 1;
    }}
</style>

<rect
    width="100%"
    height="100%"
    rx="10"
    fill="#0d1117"
/>

<text
    x="30"
    y="30"
    class="title"
>
    GitHub Repository Traffic
</text>

<text
    x="770"
    y="28"
    class="stat"
    text-anchor="end"
>
    {total_views} views · {unique_visitors} unique visitors
</text>

<line
    x1="{LEFT}"
    y1="{TOP + GRAPH_HEIGHT}"
    x2="{WIDTH - RIGHT}"
    y2="{TOP + GRAPH_HEIGHT}"
    class="axis"
/>

<line
    x1="{LEFT}"
    y1="{TOP}"
    x2="{LEFT}"
    y2="{TOP + GRAPH_HEIGHT}"
    class="axis"
/>

<polyline
    points="{view_points}"
    fill="none"
    stroke="#58a6ff"
    stroke-width="3"
/>

<polyline
    points="{unique_points}"
    fill="none"
    stroke="#3fb950"
    stroke-width="3"
/>

<text
    x="{LEFT}"
    y="{TOP - 10}"
    font-size="12"
    fill="#58a6ff"
>
    Views
</text>

<text
    x="{LEFT + 60}"
    y="{TOP - 10}"
    font-size="12"
    fill="#3fb950"
>
    Unique visitors
</text>

{date_labels}

</svg>
"""

Path("traffic.svg").write_text(svg)

print(
    f"Generated traffic.svg: "
    f"{total_views} views, "
    f"{unique_visitors} unique visitors"
)