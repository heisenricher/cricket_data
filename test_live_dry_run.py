import sys
from live_cricket_sheets import find_india_match_url, fetch_commentary

print("Detecting live match for Indian Men's Cricket Team...")
match_url = find_india_match_url()
if match_url:
    print(f"Found active match: {match_url}")
    print("Fetching commentary...")
    balls = fetch_commentary(match_url)
    print(f"Successfully fetched {len(balls)} ball entries.")
    if balls:
        print("\nLast 5 ball entries:")
        for ball in balls[-5:]:
            print(f"\nID: {ball['id']}")
            print(f"  Ball: {ball['ball']}")
            print(f"  Team: {ball['team']}")
            print(f"  Batsman: {ball['batsman']}")
            print(f"  Bowler: {ball['bowler']}")
            print(f"  Commentary: {ball['commentary']}")
    else:
        print("No ball entries found.")
else:
    print("No active Indian Men's Cricket Team match found on Cricbuzz live scores page.")
