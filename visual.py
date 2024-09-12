import logging
import os
import tempfile
from contextlib import contextmanager
from time import monotonic

import aiohttp
import cv2
import numpy as np
from screeninfo import get_monitors

screen_width, screen_height = get_monitors()[0].width, get_monitors()[0].height
TRANSITION_DURATION = 5.0
FRAME_RATE = 30


# Function to download the thumbnail and save it to a temporary file
async def download_thumbnail(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                logging.error(f"Failed to download thumbnail: {url}")
                return None
            thumb_data = await response.read()
            # logging.info(f"Downloaded thumbnail: {url}")
            return thumb_data


def fit_image_to_screen(image, screen_width, screen_height):
    height, width = image.shape[:2]
    screen_aspect = screen_width / screen_height
    image_aspect = width / height

    crop_x, crop_y = (0, 0)
    if image_aspect > screen_aspect:
        new_width = int(screen_aspect * height)
        crop_x = (width - new_width) // 2
    else:
        new_height = int(width / screen_aspect)
        crop_y = (height - new_height) // 2

    cropped_image = image[crop_y : crop_y + height, crop_x : crop_x + width]
    return cv2.resize(
        cropped_image, (screen_width, screen_height), interpolation=cv2.INTER_LINEAR
    )


# Apply blur effect to an image
def blur_image(image_data):
    np_array = np.frombuffer(image_data, np.uint8)
    image = cv2.imdecode(np_array, cv2.IMREAD_COLOR)
    blurred = cv2.GaussianBlur(image, (0, 0), 30)
    fitted_image = fit_image_to_screen(
        blurred, 1440, 900
    )  # make 1920x1080 for projection
    smoothed = cv2.blur(fitted_image, (2, 2))
    return smoothed


# Context manager for temporary image files
@contextmanager
def temporary_image_file(suffix=".jpg"):
    tmp_file = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        yield tmp_file.name
    finally:
        os.unlink(tmp_file.name)


async def display_thumbnail(image_data, info_dict, stop_event):
    try:
        if image_data is None:
            logging.error("No image data provided.")
            return

        # logging.info("Preparing to display thumbnail")
        image = blur_image(image_data)

        # Placeholder for transition logic:
        prev_image = getattr(display_thumbnail, "prev_image", None)
        display_thumbnail.prev_image = prev_image

        window_name = "cacophony"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

        # Fullscreen display
        # cv2.setWindowProperty(
        #     window_name,
        #     cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN
        # )

        start_time = monotonic()
        frame_delay = 1.0 / FRAME_RATE
        transition_complete = False

        while not stop_event.is_set() and not transition_complete:
            elapsed_time = monotonic() - start_time
            alpha = min(elapsed_time / TRANSITION_DURATION, 1.0)

            if prev_image is not None:
                transition_image = cv2.addWeighted(
                    prev_image, 1.0 - alpha, image, alpha, 0
                )
            else:
                transition_image = image

            cv2.putText(
                transition_image,
                info_dict["link"].split("https://www.")[-1],
                (10, transition_image.shape[0] - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )
            cv2.imshow(window_name, transition_image)
            cv2.waitKey(int(frame_delay * 1000))

            if alpha >= 1.0:
                transition_complete = True

        # logging.info("Transition complete or stop event set.")

        if not stop_event.is_set():
            display_thumbnail.prev_image = image

    except Exception as e:
        logging.error(f"An error occurred in display_thumbnail: {e}")
