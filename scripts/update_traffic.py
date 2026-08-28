import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


API_VERSION = "2026-03-10"

DATA_PATH = Path("data/traffic.json")
SVG_PATH = Path("docs/traffic.svg")


def github_get(endpoint: str) -> dict:
    token = os.environ["TRAFFIC_TOKEN"]
    repository = os.environ["GITHUB_REPOSITORY"]

    url = f"https://api.github.com/repos/{repository}{endpoint}"

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "repository-traffic-action",
        },
    )

    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8")
        raise RuntimeError(
            f"GitHub API request failed: {error.code} {error.reason}\n{body}"
        ) from error


def load_history() -> dict:
    if not DATA_PATH.exists():
        return {"days": {}}

    with DATA_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_history(history: dict) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)

    with DATA_PATH.open("w", encoding="utf-8") as file:
        json.dump(history, file, indent=2, sort_keys=True)
        file.write("\n")


def update_history(history: dict, views: dict, clones: dict) -> None:
    days = history.setdefault("days", {})

    for item in views.get("views", []):
        date = item["timestamp"][:10]

        days.setdefault(date, {})
        days[date]["views"] = item["count"]
        days[date]["uniqueVisitors"] = item["uniques"]

    for item in clones.get("clones", []):
        date = item["timestamp"][:10]

        days.setdefault(date, {})
        days[date]["clones"] = item["count"]
        days[date]["uniqueCloners"] = item["uniques"]


def escape_xml(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def create_polyline(
    values: list[int],
    left: float,
    top: float,
    width: float,
    height: float,
    max_value: int,
) -> str:
    if not values:
        return ""

    if len(values) == 1:
        x_values = [left]
    else:
        step = width / (len(values) - 1)
        x_values = [left + index * step for index in range(len(values))]

    points = []

    for x, value in zip(x_values, values):
        normalized = value / max_value if max_value else 0
        y = top + height - (normalized * height)
        points.append(f"{x:.1f},{y:.1f}")

    return " ".join(points)


def generate_svg(history: dict) -> None:
    repository = os.environ["GITHUB_REPOSITORY"]

    days = history.get("days", {})
    sorted_dates = sorted(days.keys())

    # Show at most the latest 30 days.
    visible_dates = sorted_dates[-30:]

    views = [days[date].get("views", 0) for date in visible_dates]
    visitors = [days[date].get("uniqueVisitors", 0) for date in visible_dates]
    clones = [days[date].get("clones", 0) for date in visible_dates]
    cloners = [days[date].get("uniqueCloners", 0) for date in visible_dates]

    total_views = sum(views)
    total_visitors = sum(visitors)
    total_clones = sum(clones)
    total_cloners = sum(cloners)

    max_graph_value = max(views + visitors + [1])

    chart_left = 55
    chart_top = 90
    chart_width = 790
    chart_height = 220

    views_points = create_polyline(
        views,
        chart_left,
        chart_top,
        chart_width,
        chart_height,
        max_graph_value,
    )

    visitors_points = create_polyline(
        visitors,
        chart_left,
        chart_top,
        chart_width,
        chart_height,
        max_graph_value,
    )

    if visible_dates:
        first_date = visible_dates[0]
        last_date = visible_dates[-1]
    else:
        first_date = "No data"
        last_date = "No data"

    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    horizontal_grid = []

    for index in range(5):
        y = chart_top + (chart_height / 4) * index
        value = round(max_graph_value * (1 - index / 4))

        horizontal_grid.append(
            f"""
            <line
                x1="{chart_left}"
                y1="{y:.1f}"
                x2="{chart_left + chart_width}"
                y2="{y:.1f}"
                stroke="#30363d"
                stroke-width="1"
            />
            <text
                x="{chart_left - 12}"
                y="{y + 5:.1f}"
                text-anchor="end"
                class="axis"
            >{value}</text>
            """
        )

    svg = f"""<svg
    xmlns="http://www.w3.org/2000/svg"
    width="900"
    height="500"
    viewBox="0 0 900 500"
    role="img"
    aria-labelledby="title description"
>
    <title id="title">Repository Traffic Analytics</title>
    <desc id="description">
        Traffic analytics for {escape_xml(repository)} showing views,
        unique visitors, clones, and unique cloners.
    </desc>

    <style>
        text {{
            font-family:
                -apple-system,
                BlinkMacSystemFont,
                "Segoe UI",
                Helvetica,
                Arial,
                sans-serif;
        }}

        .title {{
            fill: #f0f6fc;
            font-size: 24px;
            font-weight: 600;
        }}

        .subtitle {{
            fill: #8b949e;
            font-size: 13px;
        }}

        .axis {{
            fill: #8b949e;
            font-size: 11px;
        }}

        .metric {{
            fill: #f0f6fc;
            font-size: 25px;
            font-weight: 600;
        }}

        .metric-label {{
            fill: #8b949e;
            font-size: 13px;
        }}

        .legend {{
            fill: #c9d1d9;
            font-size: 12px;
        }}
    </style>

    <rect width="900" height="500" rx="12" fill="#0d1117" />

    <text x="40" y="42" class="title">
        Repository Traffic
    </text>

    <text x="40" y="66" class="subtitle">
        {escape_xml(repository)} • latest {len(visible_dates)} stored days
    </text>

    {"".join(horizontal_grid)}

    <polyline
        points="{views_points}"
        fill="none"
        stroke="#58a6ff"
        stroke-width="3"
        stroke-linecap="round"
        stroke-linejoin="round"
    />

    <polyline
        points="{visitors_points}"
        fill="none"
        stroke="#3fb950"
        stroke-width="3"
        stroke-linecap="round"
        stroke-linejoin="round"
    />

    <circle cx="610" cy="45" r="5" fill="#58a6ff" />
    <text x="622" y="49" class="legend">Views</text>

    <circle cx="690" cy="45" r="5" fill="#3fb950" />
    <text x="702" y="49" class="legend">Unique visitors</text>

    <text
        x="{chart_left}"
        y="{chart_top + chart_height + 25}"
        class="axis"
    >
        {escape_xml(first_date)}
    </text>

    <text
        x="{chart_left + chart_width}"
        y="{chart_top + chart_height + 25}"
        text-anchor="end"
        class="axis"
    >
        {escape_xml(last_date)}
    </text>

    <line
        x1="40"
        y1="355"
        x2="860"
        y2="355"
        stroke="#30363d"
    />

    <text x="65" y="405" class="metric">{total_views}</text>
    <text x="65" y="430" class="metric-label">Views</text>

    <text x="265" y="405" class="metric">{total_visitors}</text>
    <text x="265" y="430" class="metric-label">Unique visitors</text>

    <text x="505" y="405" class="metric">{total_clones}</text>
    <text x="505" y="430" class="metric-label">Clones</text>

    <text x="705" y="405" class="metric">{total_cloners}</text>
    <text x="705" y="430" class="metric-label">Unique cloners</text>

    <text x="40" y="475" class="subtitle">
        Last updated: {updated_at}
    </text>
</svg>
"""

    SVG_PATH.parent.mkdir(parents=True, exist_ok=True)
    SVG_PATH.write_text(svg, encoding="utf-8")


def main() -> None:
    print("Fetching repository traffic...")

    views = github_get("/traffic/views?per=day")
    clones = github_get("/traffic/clones?per=day")

    history = load_history()

    update_history(
        history=history,
        views=views,
        clones=clones,
    )

    save_history(history)
    generate_svg(history)

    print("Traffic analytics updated successfully.")


if __name__ == "__main__":
    main()