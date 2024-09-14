# Import necessary libraries
from bs4 import BeautifulSoup
import requests
import urllib.parse
from collections import deque
import re
import argparse
import sqlite3


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
    conn = sqlite3.connect(db_file)
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

# Function to insert emails into SQLite database
def save_to_db(cursor, conn, domain, emails):
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
        # Loop until either the maximum URL count is reached or there are no more URLs to process
        while urls:
            url = urls.popleft()

            # Add the current URL to the set of scraped URLs
            local_scraped_urls.add(url)

            # Parse the URL into its components
            parts = urllib.parse.urlsplit(url)
            base_url = '{0.scheme}://{0.netloc}'.format(parts)
            path = url[:url.rfind('/')+1] if '/' in parts.path else url

            # Validate URL before processing
            if not is_valid_url(url):
                print(f"Skipping invalid URL: {url}")
                continue

            # Print the current URL being processed
            print('[%d] Processing %s' % (len(local_scraped_urls), url))
            
            # Send a GET request to the URL with a timeout of 5 seconds
            try:
                response = requests.get(url, timeout=5)
                
                if response.status_code != 200:
                    print("Failed to retrieve response for", url)
                    break
            except:
                print("Request timed out for", url)
                continue

            # Find all email addresses in the response text and add them to the set of emails
            new_emails = set(re.findall(r"[a-z0-9\.\-+_]+@[a-z0-9\.\-+_]+\.[a-z]+", response.text, re.I))
            local_emails.update(new_emails)

            # Parse the HTML content of the response
            soup = BeautifulSoup(response.text, features="lxml")

            # Find all anchor tags in the HTML and extract their href attributes
            for anchor in soup.find_all("a"):
                link = anchor.attrs.get('href', '')  # Using .get() to handle missing 'href' attribute
                
                # Construct absolute URLs from relative URLs
                if link.startswith('/'):
                    link = base_url + link
                elif not link.startswith('http'):
                    link = path + link

                # Add new URLs to the deque if they haven't been processed or scraped before
                #extensions to ingone if it is present in a url
                exclusion_list = ['.jpg', '.jpeg', '.pdf','.png']
                if link not in urls and link not in local_scraped_urls and not any([x in link for x in exclusion_list]):
                    urls.append(link)
            
            if len(local_scraped_urls) >= max_urls:
                break
            
    except KeyboardInterrupt:
        print('[-] Closing!')

    return local_emails, local_scraped_urls


# Main function to process domains and save results to SQLite
def process_domains_and_save_to_db(domains, max_urls, cursor, conn):
    for domain in domains:
        print(f"Processing domain: {domain}")
        emails_found, _ = scrape_domain(domain, max_urls)
        
        if emails_found:
            save_to_db(cursor, conn, domain, emails_found)
        else:
            print(f"No emails found for {domain}")
            save_to_db(cursor, conn, domain, [0])

# Main Execution
if __name__ == "__main__":
    # Parse command-line arguments
    args = parse_arguments()

    # Get the list of domains from the file
    if args.inputfile:
        domains = load_domains_from_file(args.inputfile)
    else:
        print("Please provide a file with a list of domains using --inputfile")
        exit()

    # Initialize the SQLite database
    conn, cursor = init_db(args.db)

    # Get max URLs to process
    max_urls = args.maxurls

    # Process domains and save results to SQLite
    process_domains_and_save_to_db(domains, max_urls, cursor, conn)

    # Close the database connection
    conn.close()

    print("\nAll emails have been saved to the SQLite database.")

#python mail_miner2.py --inputfile domains.txt --db database.db --maxurls 20
