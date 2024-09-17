from bs4 import BeautifulSoup
import requests
import urllib.parse
from collections import deque
import re
import argparse
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed


# Function to validate URL format
def is_valid_url(url):
    parsed_url = urllib.parse.urlparse(url)
    return parsed_url.scheme in ['http', 'https'] and parsed_url.netloc != ''

# Function to parse command-line arguments
def parse_arguments():
    parser = argparse.ArgumentParser(prog="mail_miner.py", description="A tool to search for email addresses of the target domain (Email Harvester).", epilog="If no arguments are provided, the script will prompt the user to enter the required information interactively.")
    parser.add_argument("--inputfile", "-i", metavar="FILE", help="File containing list of domains (one per line)")
    parser.add_argument("--maxurls", "-murls", type=int, default=100, metavar="NUM", help="Maximum number of URLs to process per domain (default is 100)")
    parser.add_argument("--db", "-db", metavar="DB", default="emails.db", help="SQLite database file (default is emails.db)")
    parser.add_argument("--threads", "-t", type=int, default=5, help="Number of threads to use for concurrent domain processing")
    return parser.parse_args()

# Function to load domain list from a file
def load_domains_from_file(filename):
    try:
        with open(filename, 'r') as file:
            return [line.strip() for line in file if is_valid_url(line.strip())]
    except Exception as e:
        print(f"Error loading file: {e}")
        return []

# Function to connect to SQLite database and create table if not exists
def init_db(db_file):
    conn = sqlite3.connect(db_file, check_same_thread=False)  # 'check_same_thread=False' for multithreading
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS emails (
            domain TEXT,
            email TEXT,
            UNIQUE(domain, email)
        )
    ''')
    conn.commit()
    return conn, cursor

# Function to insert emails into SQLite database (thread-safe)
def save_to_db(cursor, conn, domain, emails, lock):
    with lock:
        for email in emails:
            try:
                cursor.execute("INSERT OR IGNORE INTO emails (domain, email) VALUES (?, ?)", (domain, email))
            except sqlite3.Error as e:
                print(f"Error inserting data: {e}")
        conn.commit()

# Function to scrape a domain
def scrape_domain(domain, max_urls):
    urls = deque([domain])
    local_emails = set()
    local_scraped_urls = set()

    try:
        while urls:
            url = urls.popleft()
            local_scraped_urls.add(url)

            parts = urllib.parse.urlsplit(url)
            base_url = '{0.scheme}://{0.netloc}'.format(parts)
            path = url[:url.rfind('/')+1] if '/' in parts.path else url

            if not is_valid_url(url):
                print(f"Skipping invalid URL: {url}")
                continue

            print('[%d] Processing %s' % (len(local_scraped_urls), url))

            try:
                response = requests.get(url, timeout=5)
                if response.status_code != 200:
                    print("Failed to retrieve response for", url)
                    break
            except:
                print("Request timed out for", url)
                continue

            new_emails = set(re.findall(r"[a-z0-9\.\-+_]+@[a-z0-9\.\-+_]+\.[a-z]+", response.text, re.I))
            local_emails.update(new_emails)

            soup = BeautifulSoup(response.text, features="lxml")
            for anchor in soup.find_all("a"):
                link = anchor.attrs.get('href', '')

                if link.startswith('/'):
                    link = base_url + link
                elif not link.startswith('http'):
                    link = path + link

                exclusion_list = ['.jpg', '.jpeg', '.pdf', '.png']
                if link not in urls and link not in local_scraped_urls and not any([x in link for x in exclusion_list]):
                    urls.append(link)

            if len(local_scraped_urls) >= max_urls:
                break

    except KeyboardInterrupt:
        print('[-] Closing!')

    return local_emails, local_scraped_urls

# Thread function to process a single domain
def process_single_domain(domain, max_urls, cursor, conn, lock):
    print(f"Processing domain: {domain}")
    emails_found, _ = scrape_domain(domain, max_urls)

    if emails_found:
        save_to_db(cursor, conn, domain, emails_found, lock)
    else:
        print(f"No emails found for {domain}")
        save_to_db(cursor, conn, domain, [0], lock)

# Main function to process domains concurrently and save results to SQLite
def process_domains_and_save_to_db(domains, max_urls, cursor, conn, threads):
    lock = threading.Lock()  # Create a threading lock for safe DB operations

    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = [executor.submit(process_single_domain, domain, max_urls, cursor, conn, lock) for domain in domains]
        for future in as_completed(futures):
            future.result()  # Will raise any exceptions from threads

# Main Execution
if __name__ == "__main__":
    args = parse_arguments()

    if args.inputfile:
        domains = load_domains_from_file(args.inputfile)
    else:
        print("Please provide a file with a list of domains using --inputfile")
        exit()

    conn, cursor = init_db(args.db)
    max_urls = args.maxurls
    threads = args.threads

    process_domains_and_save_to_db(domains, max_urls, cursor, conn, threads)

    conn.close()

    print("\nAll emails have been saved to the SQLite database.")

#python mail_miner.py --inputfile domains.txt --db database.db --maxurls 20 --threads 10
