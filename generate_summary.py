"""
GitHub Weekly Activity Summary
Generates a markdown summary of commits and pull requests
across dwillis, NewsAppsUMD, openelections, and Sports-Roster-Data.

Required env vars:
  GITHUB_TOKEN  - a classic PAT with repo + read:org scopes
  OUTPUT_REPO   - the repo to commit the summary to, e.g. "dwillis/weekly-summaries"
                  (leave unset to just write the file locally)
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TOKEN = os.environ.get("GITHUB_TOKEN")
if not TOKEN:
    sys.exit("GITHUB_TOKEN environment variable is required.")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

ACCOUNTS = [
    {"type": "user",  "name": "dwillis"},
    {"type": "org",   "name": "NewsAppsUMD"},
    {"type": "org",   "name": "openelections"},
    {"type": "org",   "name": "Sports-Roster-Data"},
]

SINCE = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

def paginate(url: str, params: dict = None) -> list:
    """Fetch all pages from a GitHub API endpoint."""
    results = []
    params = params or {}
    params.setdefault("per_page", 100)
    while url:
        resp = requests.get(url, headers=HEADERS, params=params)
        resp.raise_for_status()
        results.extend(resp.json())
        url = resp.links.get("next", {}).get("url")
        params = {}  # subsequent pages have params baked into the URL
    return results


def get_repos(account: dict) -> list:
    if account["type"] == "user":
        url = f"https://api.github.com/users/{account['name']}/repos"
    else:
        url = f"https://api.github.com/orgs/{account['name']}/repos"
    repos = paginate(url, {"type": "all", "sort": "pushed"})
    # Only repos pushed to in the last 7 days (quick pre-filter)
    return [
        r for r in repos
        if r.get("pushed_at") and r["pushed_at"] >= SINCE
    ]


def get_commits(repo_full_name: str) -> list:
    url = f"https://api.github.com/repos/{repo_full_name}/commits"
    try:
        commits = paginate(url, {"since": SINCE})
    except requests.HTTPError:
        return []
    return commits


def get_pull_requests(repo_full_name: str) -> list:
    url = f"https://api.github.com/repos/{repo_full_name}/pulls"
    try:
        # Closed PRs (merged) + open PRs updated this week
        closed = paginate(url, {"state": "closed", "sort": "updated", "direction": "desc"})
        open_prs = paginate(url, {"state": "open",   "sort": "updated", "direction": "desc"})
    except requests.HTTPError:
        return []

    recent_closed = [
        pr for pr in closed
        if pr.get("updated_at") and pr["updated_at"] >= SINCE
    ]
    recent_open = [
        pr for pr in open_prs
        if pr.get("updated_at") and pr["updated_at"] >= SINCE
    ]
    return recent_closed + recent_open


# ---------------------------------------------------------------------------
# Markdown builder
# ---------------------------------------------------------------------------

def fmt_date(iso: str) -> str:
    return iso[:10] if iso else "unknown"


def build_markdown(week_start: str, week_end: str, data: dict) -> str:
    lines = [
        f"# GitHub Activity Summary",
        f"**Period:** {week_start} → {week_end}",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]

    total_commits = 0
    total_prs = 0

    for account_name, repos in data.items():
        account_commits = sum(len(r["commits"]) for r in repos)
        account_prs = sum(len(r["prs"]) for r in repos)
        total_commits += account_commits
        total_prs += account_prs

        if account_commits == 0 and account_prs == 0:
            continue

        lines.append(f"## {account_name}")
        lines.append("")

        for repo in repos:
            if not repo["commits"] and not repo["prs"]:
                continue

            lines.append(f"### [{repo['name']}]({repo['url']})")
            lines.append("")

            if repo["commits"]:
                lines.append(f"**Commits ({len(repo['commits'])})**")
                lines.append("")
                for c in repo["commits"]:
                    sha = c["sha"][:7]
                    msg = c["commit"]["message"].splitlines()[0][:100]
                    author = (
                        c["commit"]["author"].get("name", "unknown")
                    )
                    date = fmt_date(c["commit"]["author"].get("date"))
                    url = c["html_url"]
                    lines.append(f"- [`{sha}`]({url}) {msg} — *{author}* ({date})")
                lines.append("")

            if repo["prs"]:
                lines.append(f"**Pull Requests ({len(repo['prs'])})**")
                lines.append("")
                for pr in repo["prs"]:
                    state = pr["state"]
                    merged = bool(pr.get("merged_at"))
                    label = "merged" if merged else state
                    title = pr["title"][:100]
                    user = pr["user"]["login"]
                    date = fmt_date(pr.get("merged_at") or pr.get("updated_at"))
                    url = pr["html_url"]
                    lines.append(f"- [#{pr['number']}]({url}) {title} ({label}) — *{user}* ({date})")
                lines.append("")

    lines.insert(4, f"**Totals:** {total_commits} commits · {total_prs} pull requests")
    lines.insert(5, "")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    week_end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    week_start = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

    data = {}

    for account in ACCOUNTS:
        print(f"Fetching repos for {account['name']}...")
        repos = get_repos(account)
        repo_data = []

        for repo in repos:
            full_name = repo["full_name"]
            print(f"  {full_name}")
            commits = get_commits(full_name)
            prs = get_pull_requests(full_name)
            if commits or prs:
                repo_data.append({
                    "name": repo["name"],
                    "url": repo["html_url"],
                    "commits": commits,
                    "prs": prs,
                })

        data[account["name"]] = repo_data

    markdown = build_markdown(week_start, week_end, data)

    # Write locally
    out_path = Path(f"summaries/summary-{week_end}.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown)
    print(f"\nSummary written to {out_path}")

    # Also print to stdout (useful for Actions logs)
    print("\n" + "=" * 60)
    print(markdown)


if __name__ == "__main__":
    main()
