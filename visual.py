import asyncio
import os
import tempfile

import cv2
import requests
import yt_dlp


# Function to get thumbnail URL from a YouTube video URL
def get_thumbnail_url(video_url):
    with yt_dlp.YoutubeDL() as ydl:
        info_dict = ydl.extract_info(video_url, download=False)
        thumbnail_url = info_dict.get("thumbnail", None)
    thumbnail_url = "/".join(thumbnail_url.rsplit("/", 1)[:-1]) + "/hqdefault.jpg"
    return thumbnail_url


# Function to download the thumbnail and save it to a temporary file
async def download_thumbnail(url):
    response = requests.get(url, stream=True)
    if response.status_code == 200:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
            for chunk in response.iter_content(1024):
                tmp_file.write(chunk)
            return tmp_file.name
    return None


# Apply blur effect to an image
def blur_image(image_path):
    # Step 1: Load the lower resolution image
    # Assuming the image is already 480x360
    image = cv2.imread(image_path)

    # Step 2: Apply Gaussian Blur
    blurred = cv2.GaussianBlur(image, (0, 0), 50)

    # Step 3: Upsample to 1080p (1920x1080)
    upscaled = cv2.resize(blurred, (1920, 1080), interpolation=cv2.INTER_LINEAR)

    smoothed = cv2.blur(upscaled, (5, 5))

    return smoothed


DURATION = 5  # Duration of the transition in seconds


# Main async function to display the images with transitions
async def display_images_with_transitions(queue):
    prev_image = None
    # Calculate the wait time for cv2.waitKey based on the desired transition duration and frame rate
    frame_rate = 60  # Number of frames per second in the transition
    total_frames = DURATION * frame_rate
    wait_time = int(1000 / frame_rate)  # Convert to milliseconds for cv2.waitKey

    while True:
        url = await queue.get()
        thumbnail_url = get_thumbnail_url(url)
        temp_image_path = await download_thumbnail(thumbnail_url)
        if temp_image_path:
            image = blur_image(temp_image_path)
            if prev_image is not None:
                # Make a seamless transition from prev_image to image
                for frame in range(total_frames):
                    alpha = frame / total_frames
                    beta = 1.0 - alpha
                    transition_image = cv2.addWeighted(
                        prev_image, beta, image, alpha, 0
                    )
                    cv2.imshow("Transition Effect", transition_image)
                    cv2.waitKey(wait_time)
            prev_image = image
            os.unlink(temp_image_path)


# Main setup
async def main():
    queue = asyncio.Queue()
    # Example URLs, replace or dynamically append these as required
    urls = [
        "https://www.youtube.com/watch?v=Taqk6UmcOzI",
        "https://www.youtube.com/watch?v=pWu7GLp0Pnk",
        "https://www.youtube.com/watch?v=YR98kk15BEE",
        "https://www.youtube.com/watch?v=-RzDSxko2tk",
        "https://www.youtube.com/watch?v=D4M9cp_yNhg",
        "https://www.youtube.com/watch?v=hVBa76RcxI8",
        "https://www.youtube.com/watch?v=7b1BEniEbWY",
        "https://www.youtube.com/watch?v=VlS-cUVnB2Q",
        "https://www.youtube.com/watch?v=OJj_UVPOPDg",
        "https://www.youtube.com/watch?v=b4J39mdB8dE",
    ]
    for url in urls:
        await queue.put(url)
    await display_images_with_transitions(queue)


if __name__ == "__main__":
    asyncio.run(main())
