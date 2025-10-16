from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions
from typing import Callable, Optional
from datetime import datetime
import asyncio
from app.config import settings


class DeepgramService:
    """Service for Deepgram real-time speech-to-text"""

    def __init__(self):
        self.api_key = settings.DEEPGRAM_API_KEY
        self.client = DeepgramClient(self.api_key) if self.api_key else None
        self.connection = None

    async def start_streaming(
        self,
        on_transcript: Callable,
        language: str = "es",
        model: str = "nova-2"
    ):
        """
        Start streaming transcription

        Args:
            on_transcript: Callback function for each transcript
            language: Language code (es, en, fr)
            model: Deepgram model to use
        """
        if not self.client:
            raise Exception("Deepgram API key not configured")

        try:
            # Configure streaming options
            options = LiveOptions(
                model=model,
                language=language,
                smart_format=True,
                interim_results=True,
                punctuate=True,
                profanity_filter=False,
                diarize=True,  # Speaker detection
                encoding="linear16",
                sample_rate=16000,
                channels=1
            )

            # Create websocket connection
            self.connection = self.client.listen.live.v("1")

            # Event handlers
            @self.connection.on(LiveTranscriptionEvents.Transcript)
            def on_message(self, result, **kwargs):
                sentence = result.channel.alternatives[0].transcript

                if len(sentence) > 0:
                    # Get speaker info if available
                    speaker = None
                    if result.channel.alternatives[0].words:
                        speaker = result.channel.alternatives[0].words[0].speaker

                    # Call the callback
                    asyncio.create_task(on_transcript({
                        "text": sentence,
                        "is_final": result.is_final,
                        "confidence": result.channel.alternatives[0].confidence,
                        "speaker": speaker,
                        "language": language,
                        "timestamp": datetime.now()
                    }))

            @self.connection.on(LiveTranscriptionEvents.Error)
            def on_error(self, error, **kwargs):
                print(f"Deepgram Error: {error}")

            # Start connection
            if self.connection.start(options) == False:
                raise Exception("Failed to start Deepgram connection")

            return self.connection

        except Exception as e:
            print(f"Error starting Deepgram: {e}")
            raise

    async def send_audio(self, audio_data: bytes):
        """Send audio chunk to Deepgram"""
        if self.connection:
            self.connection.send(audio_data)

    async def stop_streaming(self):
        """Stop the streaming connection"""
        if self.connection:
            self.connection.finish()
            self.connection = None
