import os
import sys
import time
import requests
from bs4 import BeautifulSoup
import json
import csv
import subprocess

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(REPO_DIR, "live_commentary.csv")

def find_india_match_url():
    """Auto-detects the active Indian Men's Cricket Team match URL on Cricbuzz."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        response = requests.get('https://www.cricbuzz.com/cricket-match/live-scores', headers=headers, timeout=10)
        if response.status_code != 200:
            return None
        soup = BeautifulSoup(response.text, 'html.parser')
        for link in soup.find_all('a'):
            href = link.get('href', '')
            if '/live-cricket-scores/' in href:
                text = link.text.upper()
                if ('IND' in text or 'INDIA' in text) and not any(x in text for x in ['U19', 'U-19', 'WOMEN', 'WOMENS', 'GIRLS']):
                    return 'https://www.cricbuzz.com' + href
    except Exception as e:
        print(f"Error auto-detecting match URL: {e}", file=sys.stderr)
    return None

def fetch_commentary(match_url):
    """Fetches and parses commentary from a Cricbuzz match URL."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    response = requests.get(match_url, headers=headers, timeout=10)
    if response.status_code != 200:
        return []
    soup = BeautifulSoup(response.text, 'html.parser')
    script_content = ""
    for script in soup.find_all('script'):
        content = script.string or ''
        if "matchCommentary" in content:
            script_content += content
    if not script_content:
        return []
    clean_content = script_content.replace('\\"', '"').replace('\\\\', '\\')
    target = '"matchCommentary":'
    idx = clean_content.find(target)
    if idx == -1:
        return []
    start_idx = idx + len(target)
    brace_count = 0
    end_idx = start_idx
    for i in range(start_idx, len(clean_content)):
        char = clean_content[i]
        if char == '{':
            brace_count += 1
        elif char == '}':
            brace_count -= 1
            if brace_count == 0:
                end_idx = i + 1
                break
    json_str = clean_content[start_idx:end_idx]
    try:
        commentary_dict = json.loads(json_str)
        balls = []
        for comm_id, item in commentary_dict.items():
            if item.get('commType') == 'commentary':
                balls.append({
                    'id': str(comm_id),
                    'ball': item.get('ballMetric'),
                    'innings': item.get('inningsId'),
                    'team': item.get('teamName'),
                    'batsman': item.get('batsmanDetails', {}).get('playerName', ''),
                    'bowler': item.get('bowlerDetails', {}).get('playerName', ''),
                    'commentary': item.get('commText', '')
                })
        balls.sort(key=lambda x: int(x['id']))
        return balls
    except Exception as e:
        print(f"Error parsing commentary JSON: {e}", file=sys.stderr)
        return []

def git_commit_and_push():
    """Commits and pushes the CSV updates to the GitHub repository."""
    try:
        # Add the CSV file
        subprocess.run(["git", "add", "live_commentary.csv"], cwd=REPO_DIR, check=True)
        # Check status to see if there are staged changes
        status = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_DIR, capture_output=True, text=True)
        if status.stdout.strip():
            subprocess.run(["git", "commit", "-m", "Update live cricket commentary data"], cwd=REPO_DIR, check=True)
            subprocess.run(["git", "push", "origin", "main"], cwd=REPO_DIR, check=True)
            print("Successfully committed and pushed updates to GitHub.")
        else:
            print("No new changes to commit.")
    except Exception as e:
        print(f"Git operation failed: {e}", file=sys.stderr)

def main():
    headers = ["Ball ID", "Over/Ball", "Innings", "Team", "Batsman", "Bowler", "Commentary"]
    existing_ids = set()
    
    # Read existing IDs if file exists
    if os.path.exists(CSV_FILE):
        try:
            with open(CSV_FILE, "r", newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
                if rows and len(rows) > 0:
                    existing_ids = set(row[0] for row in rows[1:] if row)
        except Exception as e:
            print(f"Error reading existing CSV: {e}", file=sys.stderr)
            
    # Write headers if file is new
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            
    match_url = None
    
    while True:
        if not match_url:
            print("Detecting live match...")
            match_url = find_india_match_url()
            if match_url:
                print(f"Match found: {match_url}")
            else:
                print("No live match found. Retrying in 1 minute...")
                time.sleep(60)
                continue
                
        print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Fetching latest commentary...")
        balls = fetch_commentary(match_url)
        
        new_balls = []
        for ball in balls:
            if ball['id'] not in existing_ids:
                new_balls.append(ball)
                existing_ids.add(ball['id'])
                
        if new_balls:
            print(f"Writing {len(new_balls)} new entries to CSV...")
            with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                for ball in new_balls:
                    writer.writerow([
                        ball['id'],
                        str(ball['ball']),
                        str(ball['innings']),
                        ball['team'],
                        ball['batsman'],
                        ball['bowler'],
                        ball['commentary']
                    ])
            # Commit and push to Git
            git_commit_and_push()
        else:
            print("No new data found.")
            
        print("Waiting 1 minute before next refresh...")
        time.sleep(60)

if __name__ == "__main__":
    main()
