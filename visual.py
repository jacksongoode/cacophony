import asyncio
import os
import tempfile
from contextlib import contextmanager

import aiohttp
import cv2

TRANSITION_DURATION = 5.0
FRAME_RATE = 30


# Function to download the thumbnail and save it to a temporary file
async def download_thumbnail(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=".jpg"
                ) as tmp_file:
                    async for chunk in response.content.iter_chunked(1024):
                        tmp_file.write(chunk)
                    return tmp_file.name
    return None


# Apply blur effect to an image
def blur_image(image_path):
    image = cv2.imread(image_path)
    blurred = cv2.GaussianBlur(image, (0, 0), 30)
    upscaled = cv2.resize(blurred, (1920, 1080), interpolation=cv2.INTER_LINEAR)
    smoothed = cv2.blur(upscaled, (2, 2))
    return smoothed


# Context manager for temporary image files
@contextmanager
def temporary_image_file(suffix=".jpg"):
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
        yield tmp_file.name
    os.unlink(tmp_file.name)


async def display_thumbnail(thumbnail_path, stop_event):
    if thumbnail_path is None:
        return

    image = blur_image(thumbnail_path)

    with temporary_image_file() as prev_thumbnail_path:
        if os.path.exists(".thumbnail.jpg"):
            os.rename(".thumbnail.jpg", prev_thumbnail_path)
        else:
            prev_thumbnail_path = None

        prev_image = cv2.imread(prev_thumbnail_path) if prev_thumbnail_path else None

        window_name = "cacophony"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        # cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

        start_time = asyncio.get_event_loop().time()
        frame_delay = 1.0 / FRAME_RATE
        transition_complete = False

        while not stop_event.is_set() and not transition_complete:
            elapsed_time = asyncio.get_event_loop().time() - start_time
            alpha = min(elapsed_time / TRANSITION_DURATION, 1.0)

            if prev_image is not None:
                transition_image = cv2.addWeighted(
                    prev_image, 1.0 - alpha, image, alpha, 0
                )
            else:
                transition_image = image

            if alpha < 1.0:
                # Overlay the URL at the bottom left of the thumbnail only once
                cv2.putText(
                    transition_image,
                    thumbnail_path,
                    (10, transition_image.shape[0] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1,
                    (255, 255, 255),
                    1,
                    cv2.LINE_AA,
                )
                cv2.imshow(window_name, transition_image)
                cv2.waitKey(int(frame_delay * 1000))
            else:
                transition_complete = True

        cv2.imwrite(".thumbnail.jpg", image)
