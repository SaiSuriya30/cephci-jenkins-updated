import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import json
import os
import re

# Dictionary to keep track of log links found
log_links_dict = {}

# Function to fetch all .log file links recursively from a given URL
def fetch_log_links(url, base_url=None, allow=True):
    if base_url is None:
        base_url = url

    # Initialize the log links for the given URL if not already present
    if url not in log_links_dict:
        log_links_dict[url] = []

    try:
        # Make a request to the URL
        response = requests.get(url)
        response.raise_for_status()
        page_content = response.text

        # Parse the page content using BeautifulSoup
        soup = BeautifulSoup(page_content, 'html.parser')

        # Iterate over all <a> tags with an href attribute
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            absolute_url = urljoin(url, href)

            # If the link is to a .log file, add it to the log_links_dict
            if href.endswith('.log'):
                if not any(log["opt_in"] == absolute_url for log in log_links_dict[url]):
                    log_links_dict[url].append({
                        "opt_in": absolute_url
                    })

            # If the link is a directory, recursively fetch links (only once per directory)
            elif href.endswith('/') and allow:
                fetch_log_links(absolute_url, base_url, False)

    except requests.RequestException as e:
        print(f"Error fetching {url}: {e}")

# Function to save command outputs to a JSON file
def save_to_json(command, output, ceph_version):
    # Extract the subcommand type (e.g., "realm", "zonegroup", etc.) from the command
    match = re.search(r'radosgw-admin (\w+)', command)
    if match:
        subcommand = match.group(1)
        # Create a unique filename based on the subcommand
        file_name = f"{subcommand}_outputs.json"

        # Check if the file exists and read existing data
        if os.path.exists(file_name):
            with open(file_name, 'r') as file:
                data = json.load(file)
        else:
            data = {"ceph_version": ceph_version, "outputs": []}

        # Append the new output to the existing data
        data["outputs"].append({
            "command": command,
            "output": output
        })

        # Write the updated data back to the file
        with open(file_name, 'w') as file:
            json.dump(data, file, indent=4)

# Function to process a single log file URL
def process_log_file(file_url, pc=set()):
    response = requests.get(file_url)
    file_path = 'temp_file.log'  # Temporary file to store downloaded log content

    try:
        response.raise_for_status()
        with open(file_path, 'wb') as file:
            file.write(response.content)

        ceph_version = None  # Variable to store the Ceph version found in the log

        with open(file_path, 'r') as file:
            lines = file.readlines()
            print("=" * 50)
            print(file_url)  # Log the file being processed
            print("=" * 50)

            # Iterate through lines to find commands and their outputs
            for i in range(len(lines)):
                if 'Execute cephadm shell -- radosgw-admin' in lines[i]:
                    # Extract Ceph version from the log
                    version_line = lines[i + 2].strip()
                    ceph_version = ".".join(version_line.split()[5].split(".")[6:9])

                    # Extract the radosgw-admin command
                    index = lines[i].find('radosgw-admin')
                    command = lines[i][index:].rstrip("\n")

                    # Skip already processed commands
                    if command in pc:
                        continue

                    stack = []  # Stack to track JSON structure
                    json_start = None  # Track the start of JSON content
                    json_content = ""

                    # Find and extract JSON output for the command
                    for j in range(i + 1, len(lines)):
                        for char in lines[j]:
                            if char == '{':
                                if not stack:
                                    json_start = j
                                stack.append('{')
                            if stack:
                                json_content += char
                            if char == '}':
                                stack.pop()
                                if not stack:
                                    break
                        if not stack and json_content:
                            break

                    if json_content:
                        # Clean and parse JSON content
                        cleaned_output_line = (
                            json_content.replace("'", "\"")
                            .replace("True", "true")
                            .replace("False", "false")
                            .strip()
                        )

                        try:
                            json_output = json.loads(cleaned_output_line)
                        except json.JSONDecodeError:
                            json_output = None

                        # Save the JSON output if valid
                        if json_output:
                            save_to_json(command, json_output, ceph_version)
                            pc.add(command)

        os.remove(file_path)  # Remove the temporary log file

    except requests.RequestException as e:
        print(f"Failed to download file at url {file_url}: {e}")

# Function to process all log files starting from the base URL
def process_all_log_files(url):
    fetch_log_links(url)  # Fetch all .log file links recursively
    pc = set()  # Set to track processed commands
    for directories in log_links_dict:
        log_files_dict_list = log_links_dict[directories]

        # Process each .log file
        for log_files_dict in log_files_dict_list:
            process_log_file(log_files_dict["opt_in"], pc)

# Base URL to start processing logs
url = "http://magna002.ceph.redhat.com/cephci-jenkins/results/openstack/RH/8.0/rhel-9/Regression/19.2.0-12/rgw/36/"
process_all_log_files(url)
