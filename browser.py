import time

import orjson
import PySide2
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.firefox_profile import FirefoxProfile
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import StaleElementReferenceException
from selenium.common.exceptions import WebDriverException
from selenium.common.exceptions import NoSuchWindowException

prof_path = "/Users/jacksongoode/Library/Application Support/Firefox/Profiles/rqfiwwkd.Selenium"
profile = FirefoxProfile(prof_path)
profile.set_preference("extensions.lastAppBuildId", "<apppID> -1 ") # workaround for extenion bug
driver = webdriver.Firefox(firefox_profile=profile)

# try:
#     driver = webdriver.Firefox(executable_path='resources/geckodriver')
# except:
#     driver = webdriver.Chrome(executable_path='resources/chromedriver')

ignored_exceptions = (NoSuchElementException, StaleElementReferenceException)

links = {}
try:
    with open("resources/links.json", "rb") as f:
        links = orjson.loads(f.read())
except FileNotFoundError:
    print("No links.json found, creating anew")

try:
    driver.get("https://youtube.com/")

    while True: # keep open indefinately
        # Add current url as visited
        cur_url = driver.current_url
        if cur_url.startswith('https://www.youtube.com/watch?v=') and len(cur_url) == 43:
            if cur_url not in links:
                links[cur_url] = [0, 1] # (seen, visited)
            else:
                links[cur_url][1] += 1 # tally visited

        try:
            # Look for links and add as seen
            elems = []
            elems = driver.find_elements_by_xpath("//a[starts-with(@href, '/watch?v=')]")

            for elem in elems:
                href = elem.get_attribute("href")
                if len(href) == 43:
                    if href not in links:
                        links[href] = [1, 0] 
                        print(href)
                    else:
                        links[href][0] += 1 # tally seen
            
            # Wait (up to two hours) for user input on a page
            print('Waiting for new page...')
            WebDriverWait(driver, 7200, ignored_exceptions=ignored_exceptions).until(EC.url_changes(cur_url))
            
            # Save to json once new page begins to load
            with open("resources/links.json", "wb") as f:
                f.write(orjson.dumps(links))

            time.sleep(1) # let page load a bit before collecting links


        except StaleElementReferenceException as e: # suppress errors that appear to be unrelated
                print('Stale element!')
                pass

except (KeyboardInterrupt, WebDriverException, NoSuchWindowException):
    print("Quitting...")

finally:
    driver.quit()
    print("Driver killed")