import asyncio
import os

from dotenv import load_dotenv
from google import genai


load_dotenv()

model = os.environ["GEMINI_LIVE_MODEL"]

#create gemini api client using the api key stored in env and read the key
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


async def main():
    # tells gemini we want to generate audio and text transcription of the response
    config = {
        "response_modalities": ["AUDIO"],
        "output_audio_transcription": {},
    }

    print(f"Connecting to Gemini Live using {model}...")

    # open asynchronus gemini live connection
    async with client.aio.live.connect(
        model=model,
        config=config,
    ) as session:
        print("Gemini Live session connected successfully.")

        # We are sending text for now so we can test Gemini
        # without involving microphones or Twilio audio yet.
        message = (
            "You are a patient calling a doctor's office. "
            "Say: Hi, I'd like to schedule an appointment."
        )

        # send message to active gemini session
        await session.send_client_content(
            turns={
                "role": "user",
                "parts": [{"text": message}],
            },
            # user finished so tell gemini it can talk now
            turn_complete=True,
        )

        print("Prompt sent. Waiting for Gemini...")

        async for response in session.receive():
            # Print Gemini's transcription of its spoken response.
            if (
                response.server_content
                and response.server_content.output_transcription
            ):
                transcript = response.server_content.output_transcription.text
                print(f"Gemini said: {transcript}")

            # Check whether Gemini returned actual audio data.
            if response.data:
                print(f"Received audio chunk: {len(response.data)} bytes")


if __name__ == "__main__":
    asyncio.run(main())