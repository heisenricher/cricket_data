import os
import sys
import time
import requests
from bs4 import BeautifulSoup
import json
import csv
import re
import hashlib
import subprocess

REPO_DIR = os.path.dirname(os.path.abspath(__file__))

def get_match_filename(href):
    """Generates a clean match filename like eng_vs_ind_3rd_odi(19-07-2026).csv from match URL."""
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
        
    date_str = time.strftime("%d-%m-%Y")
    return f"{clean_slug}({date_str}).csv"

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
                    
                    is_completed = any(x in match_name.lower() for x in ["won by", "won", "tied", "drawn", "abandoned", "no result", "ends in a draw"])
                    
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

def fetch_commentary_html_fallback(soup):
    """Fallback method: parses raw HTML commentary divs if JSON state is not present."""
    balls = []
    print("Using HTML parsing fallback method...")
    # Cricbuzz commentary lines usually have a pattern: '16.2 Bowler to Batsman, description'
    for div in soup.find_all('div'):
        text = div.text.strip()
        if not text:
            continue
        # Match text starting with over e.g., '16.2'
        match = re.match(r'^(\d+\.\d+)\s*(.*?)$', text)
        if match:
            over_num = match.group(1)
            rest = match.group(2).strip()
            if " to " in rest and "," in rest:
                comm_text = rest
                parts = rest.split(" to ", 1)
                bowler = parts[0].strip()
                subparts = parts[1].split(",", 1)
                batsman = subparts[0].strip()
                # Generate unique ID based on hash of over + commentary to avoid duplicates
                comm_id = hashlib.md5(f"{over_num}_{comm_text}".encode('utf-8')).hexdigest()
                balls.append({
                    'id': comm_id,
                    'ball': over_num,
                    'innings': '1', # default fallback innings
                    'team': '',
                    'batsman': batsman,
                    'bowler': bowler,
                    'commentary': over_num + " " + comm_text
                })
    return balls

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
        
        # Try Next.js JSON state parsing first (highly accurate)
        script_content = ""
        for script in soup.find_all('script'):
            content = script.string or ''
            if "matchCommentary" in content:
                script_content += content
                
        if script_content:
            clean_content = script_content.replace('\\"', '"').replace('\\\\', '\\')
            target = '"matchCommentary":'
            idx = clean_content.find(target)
            if idx != -1:
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
                if balls:
                    return balls
        
        # Fallback if JSON state was not found or was empty
        return fetch_commentary_html_fallback(soup)
    except Exception as e:
        print(f"Error parsing commentary for {match_url}: {e}", file=sys.stderr)
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

def cleanup_match_csv(csv_path):
    """Cleans up the match CSV after the match ends:
    - Removes the 'Ball ID' column.
    - Removes non-ball rows (e.g. over summaries, drinks, general commentary).
    - Sorts rows chronologically by Innings and Over/Ball.
    - Saves the cleaned CSV.
    """
    if not os.path.exists(csv_path):
        return
        
    print(f"Starting post-match cleanup for: {csv_path}")
    headers = ["Over/Ball", "Innings", "Team", "Batsman", "Bowler", "Commentary"]
    cleaned_rows = []
    
    try:
        with open(csv_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
            if not rows or len(rows) <= 1:
                return
                
            orig_headers = rows[0]
            try:
                over_idx = orig_headers.index("Over/Ball")
                innings_idx = orig_headers.index("Innings")
                team_idx = orig_headers.index("Team")
                batsman_idx = orig_headers.index("Batsman")
                bowler_idx = orig_headers.index("Bowler")
                comm_idx = orig_headers.index("Commentary")
            except ValueError:
                # Already cleaned or headers mismatch
                print("CSV already cleaned or headers mismatch.")
                return
                
            for row in rows[1:]:
                if not row or len(row) <= max(over_idx, comm_idx):
                    continue
                over_val = row[over_idx].strip()
                # Check if it's a valid ball count row (must be in format X.Y e.g. 16.5)
                if re.match(r'^\d+\.\d+$', over_val):
                    cleaned_rows.append({
                        'over': float(over_val),
                        'innings': int(row[innings_idx]) if row[innings_idx].isdigit() else 1,
                        'row_data': [
                            row[over_idx],
                            row[innings_idx],
                            row[team_idx],
                            row[batsman_idx],
                            row[bowler_idx],
                            row[comm_idx]
                        ]
                    })
                    
        if cleaned_rows:
            # Sort chronologically: Innings first, then Over/Ball
            cleaned_rows.sort(key=lambda x: (x['innings'], x['over']))
            
            # Write back the cleaned data
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                for row in cleaned_rows:
                    writer.writerow(row['row_data'])
            print(f"Successfully cleaned and formatted {csv_path}. Kept {len(cleaned_rows)} ball entries.")
    except Exception as e:
        print(f"Error during CSV cleanup: {e}", file=sys.stderr)

def main():
    headers = ["Ball ID", "Over/Ball", "Innings", "Team", "Batsman", "Bowler", "Commentary"]
    # Dict to keep track of completed match IDs so we don't query them repeatedly
    completed_matches = {}
    
    # Read duration limit from environment (0 = infinite)
    run_duration = int(os.getenv("RUN_DURATION", "0"))
    start_time = time.time()
    
    print("Starting Live Cricket GitHub Sync daemon...")
    while True:
        if run_duration > 0 and (time.time() - start_time) / 60 >= run_duration:
            print(f"Run duration of {run_duration} minutes reached. Exiting gracefully.")
            break
            
        # Wrap entire loop iteration in try-except to ensure the API/sync script never terminates
        try:
            print("\n--- Scanning for International Men's matches on Cricbuzz ---")
            live_matches = find_international_matches()
            print(f"Found {len(live_matches)} matches in scope.")
            
            changed_files = []
            
            for m_id, m in live_matches.items():
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
                    print(f"Match {m['name']} has ended. Marking as completed and running post-match cleanup...")
                    completed_matches[m_id] = True
                    cleanup_match_csv(csv_path)
                    if m['filename'] not in changed_files:
                        changed_files.append(m['filename'])
                    
            if changed_files:
                git_commit_and_push(changed_files)
            else:
                print("No new ball-by-ball entries found across all matches.")
                
        except Exception as main_loop_error:
            print(f"[FATAL LOOP ERROR] {main_loop_error}. Restarting cycle in 1 minute...", file=sys.stderr)
            
        print("Waiting 1 minute before next refresh...")
        time.sleep(60)

if __name__ == "__main__":
    main()
