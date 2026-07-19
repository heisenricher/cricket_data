import os
import sys
import time
import requests
from bs4 import BeautifulSoup
import json
import gspread
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

SCRATCH_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_ACCOUNT_FILE = os.path.join(SCRATCH_DIR, "service_account.json")
OAUTH_CLIENT_FILE = os.path.join(SCRATCH_DIR, "credentials.json")

def authenticate():
    """Authenticates with Google Sheets API."""
    if os.path.exists(SERVICE_ACCOUNT_FILE):
        from google.oauth2 import service_account
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=scopes
        )
        return gspread.authorize(creds)
    elif os.path.exists(OAUTH_CLIENT_FILE):
        from google_auth_oauthlib.flow import InstalledAppFlow
        import pickle
        from google.auth.transport.requests import Request
        
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        token_path = os.path.join(SCRATCH_DIR, "token.pickle")
        creds = None
        if os.path.exists(token_path):
            with open(token_path, 'rb') as token:
                creds = pickle.load(token)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(OAUTH_CLIENT_FILE, scopes)
                creds = flow.run_local_server(port=0)
            with open(token_path, 'wb') as token:
                pickle.dump(creds, token)
        return gspread.authorize(creds)
    else:
        raise FileNotFoundError("No Google Sheets credentials file (service_account.json or credentials.json) found.")

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
                # Match IND or INDIA but exclude U19, Women, etc.
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
        print(f"Failed to fetch match page: {response.status_code}", file=sys.stderr)
        return []
        
    soup = BeautifulSoup(response.text, 'html.parser')
    script_content = ""
    for script in soup.find_all('script'):
        content = script.string or ''
        if "matchCommentary" in content:
            script_content += content
            
    if not script_content:
        return []
        
    # Unescape escaped quotes
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
        # Sort chronologically by ID/timestamp
        balls.sort(key=lambda x: int(x['id']))
        return balls
    except Exception as e:
        print(f"Error parsing commentary JSON: {e}", file=sys.stderr)
        return []

def main():
    # Load sheet name/URL from environment or arguments
    sheet_identifier = None
    if len(sys.argv) > 1:
        sheet_identifier = sys.argv[1]
    else:
        sheet_identifier = os.getenv("SPREADSHEET_NAME_OR_URL")
        
    if not sheet_identifier:
        print("[ERROR] Please provide the Google Sheet name or URL as an argument or in .env as SPREADSHEET_NAME_OR_URL.")
        sys.exit(1)
        
    print("Authenticating with Google Sheets...")
    try:
        gc = authenticate()
    except Exception as e:
        print(f"[ERROR] Authentication failed: {e}")
        print("Please set up your credentials files in the scratch directory first.")
        sys.exit(1)
    
    print(f"Opening spreadsheet: {sheet_identifier}")
    try:
        if "docs.google.com/spreadsheets" in sheet_identifier:
            sh = gc.open_by_url(sheet_identifier)
        else:
            sh = gc.open(sheet_identifier)
    except Exception as e:
        print(f"[ERROR] Could not open spreadsheet: {e}")
        print("Make sure you shared the sheet with the Service Account email if using a Service Account.")
        sys.exit(1)
        
    # Use first worksheet
    worksheet = sh.get_worksheet(0)
    
    # Initialize sheet if empty
    headers = ["Ball ID", "Over/Ball", "Innings", "Team", "Batsman", "Bowler", "Commentary"]
    existing_rows = worksheet.get_all_values()
    if not existing_rows or not existing_rows[0]:
        print("Sheet is empty. Writing headers...")
        worksheet.append_row(headers)
        existing_ids = set()
    else:
        # Extract existing Ball IDs (Column A) to prevent duplicates
        existing_ids = set(row[0] for row in existing_rows[1:] if row)
        
    print(f"Initialized with {len(existing_ids)} existing ball entries in sheet.")
    
    match_url = None
    
    while True:
        # Auto-detect match URL if not found or periodically check
        if not match_url:
            print("Detecting live match for Indian Men's Cricket Team...")
            match_url = find_india_match_url()
            if match_url:
                print(f"Found active match: {match_url}")
            else:
                print("No active Indian Men's Cricket Team match found. Checking again in 1 minute...")
                time.sleep(60)
                continue
                
        print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Fetching latest ball-by-ball commentary...")
        balls = fetch_commentary(match_url)
        
        new_rows = []
        for ball in balls:
            if ball['id'] not in existing_ids:
                row_data = [
                    ball['id'],
                    str(ball['ball']),
                    str(ball['innings']),
                    ball['team'],
                    ball['batsman'],
                    ball['bowler'],
                    ball['commentary']
                ]
                new_rows.append(row_data)
                existing_ids.add(ball['id'])
                
        if new_rows:
            print(f"Adding {len(new_rows)} new ball entries to sheet...")
            worksheet.append_rows(new_rows)
        else:
            print("No new ball entries found.")
            
        print("Waiting 1 minute before next refresh...")
        time.sleep(60)

if __name__ == "__main__":
    main()
