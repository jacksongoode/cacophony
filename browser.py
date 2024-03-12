import os
import platform
import re
import time
import traceback
import zipfile
from urllib.request import urlretrieve

import orjson
import requests
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    NoSuchWindowException,
    StaleElementReferenceException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By


def load_links():
    try:
        with open("resources/links.json", "rb") as f:
            return orjson.loads(f.read())
    except FileNotFoundError:
        print("No links.json found, creating anew")
        return {}


def save_links(links):
    os.makedirs("resources", exist_ok=True)
    with open("resources/links.json", "wb") as f:
        f.write(orjson.dumps(links))


def ask_user_permission(prompt):
    """Ask user for permission with a yes/no question."""
    valid_responses = {"yes": True, "y": True, "no": False, "n": False}
    while True:
        user_input = input(prompt).lower()
        if user_input in valid_responses:
            return valid_responses[user_input]
        else:
            print("Please answer with 'yes/y' or 'no/n'.")


def check_chromedriver_exists():
    """
    Check if the ChromeDriver exists in the drivers folder.
    Returns the path if found, otherwise None.
    """
    drivers_folder = "drivers"
    os.makedirs(drivers_folder, exist_ok=True)  # Ensure drivers folder exists

    # Adjust executable name depending on the operating system
    chromedriver_name = (
        "chromedriver.exe" if platform.system().lower() == "windows" else "chromedriver"
    )
    chromedriver_path = os.path.join(drivers_folder, chromedriver_name)

    if os.path.exists(chromedriver_path):
        return chromedriver_path
    return None


def download_and_extract_chromedriver(download_url, extract_path="drivers"):
    if not os.path.exists(extract_path):
        os.makedirs(extract_path)
    zip_path = os.path.join(extract_path, "chromedriver.zip")
    urlretrieve(download_url, zip_path)

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        # Extract only the chromedriver executable without any parent folders
        for member in zip_ref.infolist():
            filename = member.filename
            if "chromedriver" in filename and not member.is_dir():
                # Extract only the chromedriver file directly to the extract_path
                member.filename = os.path.basename(filename)
                zip_ref.extract(member, extract_path)

    # Clean up zip file after extraction
    os.remove(zip_path)

    chromedriver_path = os.path.join(extract_path, "chromedriver")

    # Check if the system is Windows, adjust the chromedriver_path accordingly
    if platform.system().lower() == "windows":
        chromedriver_path += ".exe"

    # trunk-ignore(bandit/B103)
    os.chmod(chromedriver_path, 0o755)  # Make chromedriver executable

    return chromedriver_path


def setup_chrome_driver():
    chromedriver_path = check_chromedriver_exists()
    if chromedriver_path:
        return chromedriver_path

    if not ask_user_permission("Download and setup ChromeDriver? [y/n]"):
        raise Exception("User declined to download ChromeDriver.")

    response = requests.get(
        "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json",
        timeout=60,
    )
    response_data = response.json()
    latest_version_data = response_data["channels"]["Stable"]["downloads"][
        "chromedriver"
    ]

    # Determine the platform
    os_name = platform.system().lower()
    arch = platform.machine()
    if os_name == "darwin":
        platform_key = "mac-arm64" if arch == "arm64" else "mac-x64"
    elif os_name == "linux":
        platform_key = "linux64"
    elif os_name == "windows":
        platform_key = "win64" if "64" in arch else "win32"
    else:
        raise Exception("Unsupported platform")

    # Find the download URL
    for download in latest_version_data:
        if download["platform"] == platform_key:
            chromedriver_url = download["url"]
            break
    else:
        raise Exception("Failed to find a ChromeDriver download for this platform.")

    return download_and_extract_chromedriver(chromedriver_url)


def setup_browser(driver_path):
    """
    Set up Chrome WebDriver with the specified options.

    :param driver_path: Path to the ChromeDriver executable
    :param detach: If True, the browser stays open after the script ends
    :return: The initialized WebDriver instance
    """
    options = Options()
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    service = Service(executable_path=driver_path)
    driver = webdriver.Chrome(service=service, options=options)

    return driver


def valid_youtube_watch_link_regex(url):
    """
    Check if the URL is a valid YouTube watch URL using the provided regular expression.

    Args:
        url (str): The URL to be checked.

    Returns:
        bool: True if the URL is a valid YouTube watch URL according to the regex, False otherwise.
    """
    return bool(re.match(r"^(https?:\/\/)?(www\.)?youtu(be\.com|\.be)\/.+"), url)


def increment_link(links, url, current=False):
    # if valid_youtube_watch_link_regex(url):
    if url in links:
        if current:
            # Increment visits only
            links[url] = (links[url][0] + 1, links[url][1])
        else:
            # Increment seen count only
            links[url] = (links[url][0], links[url][1] + 1)
    else:
        links[url] = (1, 0) if current else (0, 1)

    return links


def is_browser_open(driver):
    try:
        # Attempt a non-intrusive command to check browser status
        _ = driver.current_url
        return True
    except WebDriverException:
        # If a WebDriverException is raised, assume the browser is closed
        return False


def scrape_links(driver, links, check_interval=2):
    """
    Scrape links with a periodic check within the current page, adding unseen links to the links dictionary.

    Args:
        driver: Selenium WebDriver instance.
        links: Dictionary of links to be updated.
        check_interval: Interval (in seconds) to wait between checks for new links.
    """
    previous_hrefs = set()  # Tracks hrefs found in the previous iteration
    last_incremented_url = (
        None  # Tracks the last URL for which the link count was incremented
    )

    try:
        while True:
            if not is_browser_open(driver):
                print("Browser window is closed. Exiting loop.")
                break

            current_url = driver.current_url

            # Increment link count for the current page URL only once when navigated to a new page
            if current_url != last_incremented_url:
                links = increment_link(links, current_url, current=True)
                last_incremented_url = current_url
                previous_hrefs.clear()  # Clear previously seen hrefs on navigating to a new page

            # Find all watch?v= links on the current page, considering their length
            hrefs = set()
            for elem in driver.find_elements(
                By.XPATH, "//a[starts-with(@href, '/watch?v=')]"
            ):
                try:
                    href = elem.get_attribute("href")
                    if href:
                        hrefs.add(href.split("&")[0])
                except StaleElementReferenceException:
                    continue

            # Identify new links as those not seen in the previous iteration
            new_hrefs = hrefs - previous_hrefs
            for href in new_hrefs:
                links = increment_link(links, href, current=False)

            # Prepare for the next iteration
            previous_hrefs = hrefs

            save_links(links)  # Persist the updated links dictionary

            time.sleep(check_interval)  # Wait before checking the page again

    except WebDriverException as e:
        print(f"A WebDriver error occurred: {e.__class__.__name__}: {e}")
        traceback.print_exc()
    except KeyboardInterrupt:
        print("Script interrupted by user.")
    except Exception as e:
        print(f"An unexpected error occurred: {e.__class__.__name__}: {e}")
        traceback.print_exc()


def main():
    links = load_links()
    chromedriver_path = setup_chrome_driver()
    driver = setup_browser(chromedriver_path)

    driver.get("https://www.youtube.com")
    try:
        scrape_links(driver, links)
    finally:
        save_links(links)  # Ensure links are saved before exiting
        print("Driver exiting...")


if __name__ == "__main__":
    main()
