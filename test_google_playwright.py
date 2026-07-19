import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        print("Launching browser...")
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        print("Navigating to Google Search...")
        await page.goto("https://www.google.com/search?q=live+cricket+score&hl=en", wait_until="networkidle")
        
        # Wait a moment for dynamic widgets to render
        await page.wait_for_timeout(2000)
        
        print("Extracting page text...")
        text = await page.evaluate("() => document.body.innerText")
        
        # Print first 2000 characters of page text
        print("\n--- Google Page Text Snippet ---")
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        for line in lines[:150]:
            print(line)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
