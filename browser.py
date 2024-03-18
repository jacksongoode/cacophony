import logging
import os
import platform
import random
import re
import time
import traceback
import zipfile
from urllib.parse import parse_qs, urlparse
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
        logging.info("No links.json found, creating anew")
        return {}


def save_links(links):
    os.makedirs("resources", exist_ok=True)
    with open("resources/links.json", "wb") as f:
        f.write(orjson.dumps(links))


def ask_user_permission(prompt):
    """Ask user for permission with a yes/no question."""
    while True:
        user_input = input(f"{prompt} ").strip().lower()
        if user_input == "y":
            return True
        elif user_input == "n":
            return False
        else:
            print("Invalid input. Please enter 'y' or 'n'.")


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


def clean_url(url):
    """
    Clean the URL to remove any additional parameters and return only the video ID.

    Args:
        url: The YouTube video URL.

    Returns:
        The cleaned URL containing only the video ID.
    """
    parsed_url = urlparse(url)
    video_id = parse_qs(parsed_url.query).get("v", [None])[0]
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    return None


def increment_link(links, url, current=False):
    cleaned_url = clean_url(url)
    if cleaned_url:
        if cleaned_url in links:
            if current:
                # Increment visits only
                links[cleaned_url] = (links[cleaned_url][0] + 1, links[cleaned_url][1])
            else:
                # Increment seen count only
                links[cleaned_url] = (links[cleaned_url][0], links[cleaned_url][1] + 1)
        else:
            links[cleaned_url] = (1, 0) if current else (0, 1)
    return links


def is_browser_open(driver):
    try:
        # Attempt a non-intrusive command to check browser status
        _ = driver.current_url
        return True
    except (WebDriverException, NoSuchWindowException):
        # If a WebDriverException or NoSuchWindowException is raised, assume the browser is closed
        return False


def drive_mode(driver, links, check_interval=2):
    """
    Scrape links with a periodic check within the current page, adding unseen links to the links dictionary.

    Args:
        driver: Selenium WebDriver instance.
        links: Dictionary of links to be updated.
        check_interval: Interval (in seconds) to wait between checks for new links.
    """
    session_active = True
    previous_hrefs = set()
    last_incremented_url = None

    try:
        while session_active:
            if not is_browser_open(driver):
                logging.info("Browser window is closed. Exiting loop.")
                session_active = False
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

            save_links(links)

            previous_hrefs = hrefs
            time.sleep(check_interval)  # Wait before checking the page again

    except WebDriverException as e:
        logging.error(f"A WebDriver error occurred: {e.__class__.__name__}: {e}")
        traceback.print_exc()
    except KeyboardInterrupt:
        logging.error("Script interrupted by user.")
        session_active = False
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e.__class__.__name__}: {e}")
        traceback.print_exc()

    return session_active


def random_mode(driver, links, max_duration=14400):
    """
    Randomly navigate through YouTube links and related videos.

    Args:
        driver: Selenium WebDriver instance.
        links: Dictionary to store the collected links.
        max_duration: Maximum duration in seconds to run the random mode (default: 14400).
    """
    session_active = True  # Initialize the session_active flag
    start_time = time.time()
    current_url = ""

    try:
        while session_active and time.time() - start_time < max_duration:
            if not is_browser_open(driver):
                logging.info("Browser window is closed. Exiting loop.")
                session_active = False
                break

            # Perform a random number of human-like scrolls
            num_scrolls = random.randint(3, 6)
            for _ in range(num_scrolls):
                scroll_amount = random.randint(200, 400)
                driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
                time.sleep(random.uniform(0.5, 1.5))

            # Find and click on a random related video link
            related_links = driver.find_elements(
                By.XPATH, "//a[contains(@href, '/watch?v=')]"
            )

            if related_links:
                # Increment seen count for all collected links
                for link in related_links:
                    link_href = link.get_attribute("href")
                    increment_link(links, link_href)

                # Save the updated links dictionary
                save_links(links)

                # Select a totally random link and navigate to it
                current_url = random.choice(list(links))
                logging.info(f"Navigating: {current_url}")
                driver.get(current_url)
                increment_link(links, current_url, current=True)

                time.sleep(random.uniform(2, 4))
            else:
                logging.warning(
                    f"No related links found on {current_url}. Reloading..."
                )
                driver.refresh()

    except KeyboardInterrupt:
        logging.error("Script interrupted by user.")
        session_active = False
    except Exception as e:
        logging.error(f"Error occurred: {str(e)}. Reloading...")
        driver.refresh()

    logging.info("Random mode completed.")
    return session_active


def main():
    links = load_links()

    if ask_user_permission("Enter random mode? [y/n]"):
        mode = "random"
    else:
        mode = "drive"

    chromedriver_path = setup_chrome_driver()
    driver = setup_browser(chromedriver_path)

    if mode == "drive":
        # Scrape links while driving
        driver.get("https://www.youtube.com")
        drive_mode(driver, links)
    else:
        # Random mode
        driver.get("https://www.youtube.com/trending")
        random_mode(driver, links)

    logging.INFO("Driver exiting...")
    driver.quit()


if __name__ == "__main__":
    main()
