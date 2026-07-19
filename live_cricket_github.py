import os
import sys
import time
import requests
from bs4 import BeautifulSoup
import json
import csv
import subprocess

REPO_DIR = os.path.dirname(os.path.abspath(__file__))

def get_match_filename(href):
    """Generates a clean match filename like eng_vs_ind_3rd_odi.csv from match URL."""
    slug = href.split('/')[-1]
    slug_parts = slug.split('-')
    truncated_parts = []
    for part in slug_parts:
        truncated_parts.append(part.lower())
        if part.lower() in ['odi', 't20i', 'test']:
            break
    # If the format wasn't found in parts, fall back to the whole slug
    if not truncated_parts or not any(x in truncated_parts for x in ['odi', 't20i', 'test']):
        clean_slug = slug.replace('-', '_')
    else:
        clean_slug = "_".join(truncated_parts)
    return f"{clean_slug}.csv"

def find_international_matches():
    """Auto-detects active/upcoming International Men's matches on Cricbuzz."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    matches = {}
    try:
        response = requests.get('https://www.cricbuzz.com/cricket-match/live-scores', headers=headers, timeout=10)
        if response.status_code != 200:
            return {}
        soup = BeautifulSoup(response.text, 'html.parser')
        for link in soup.find_all('a'):
            href = link.get('href', '')
            if '/live-cricket-scores/' in href:
                slug = href.split('/')[-1].lower()
                # Exclude youth, women's, unofficial, warmups, and league matches
                exclude_keywords = ['u19', 'u-19', 'women', 'wmn', 'girls', 'unofficial', 'warm-up', 'warmup', 'youth', 'select-xi', 'xi']
                if any(kw in slug for kw in exclude_keywords):
                    continue
                
                # Check for international formats
                if any(fmt in slug for fmt in ['odi', 't20i', 'test']):
                    match_id = href.split('/')[-2]
                    match_name = link.text.strip().replace('\n', ' ')
                    if not match_name:
                        match_name = slug.replace('-', ' ').title()
                    
                    is_completed = any(x in match_name.lower() for x in ["won by", "won", "tied", "drawn", "abandoned", "no result", "ends in a draw", "won"])
                    
                    matches[match_id] = {
                        'id': match_id,
                        'name': match_name,
                        'url': 'https://www.cricbuzz.com' + href,
                        'filename': get_match_filename(href),
                        'completed': is_completed
                    }
    except Exception as e:
        print(f"Error auto-detecting matches: {e}", file=sys.stderr)
    return matches

def fetch_commentary(match_url):
    """Fetches and parses commentary from a Cricbuzz match URL."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
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
        print(f"Error parsing commentary JSON for {match_url}: {e}", file=sys.stderr)
        return []

def git_commit_and_push(changed_files):
    """Commits and pushes the modified CSVs to the GitHub repository."""
    try:
        for f in changed_files:
            subprocess.run(["git", "add", f], cwd=REPO_DIR, check=True)
            
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
    # Dict to keep track of completed match IDs so we don't query them repeatedly
    completed_matches = {}
    
    while True:
        print("\n--- Scanning for International Men's matches on Cricbuzz ---")
        live_matches = find_international_matches()
        print(f"Found {len(live_matches)} matches in scope.")
        
        changed_files = []
        
        for m_id, m in live_matches.items():
            # If this match was previously marked completed and we already processed it, skip
            if m_id in completed_matches:
                continue
                
            csv_path = os.path.join(REPO_DIR, m['filename'])
            existing_ids = set()
            
            # Read existing IDs if file exists
            if os.path.exists(csv_path):
                try:
                    with open(csv_path, "r", newline="", encoding="utf-8") as f:
                        reader = csv.reader(f)
                        rows = list(reader)
                        if rows and len(rows) > 0:
                            existing_ids = set(row[0] for row in rows[1:] if row)
                except Exception as e:
                    print(f"Error reading existing CSV {m['filename']}: {e}", file=sys.stderr)
                    
            # Write headers if file is new
            if not os.path.exists(csv_path):
                with open(csv_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(headers)
                    
            print(f"Fetching commentary for: {m['name']} ({m['filename']})")
            balls = fetch_commentary(m['url'])
            
            new_balls = []
            for ball in balls:
                if ball['id'] not in existing_ids:
                    new_balls.append(ball)
                    existing_ids.add(ball['id'])
                    
            if new_balls:
                print(f"Writing {len(new_balls)} new entries to {m['filename']}...")
                with open(csv_path, "a", newline="", encoding="utf-8") as f:
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
                if m['filename'] not in changed_files:
                    changed_files.append(m['filename'])
                    
            if m['completed']:
                print(f"Match {m['name']} has ended. Marking as completed.")
                completed_matches[m_id] = True
                
        if changed_files:
            git_commit_and_push(changed_files)
        else:
            print("No new ball-by-ball entries found across all matches.")
            
        print("Waiting 1 minute before next refresh...")
        time.sleep(60)

if __name__ == "__main__":
    main()
