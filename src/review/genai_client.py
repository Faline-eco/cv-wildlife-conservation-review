# wildcv_review/genai_client.py
import asyncio, random, json, logging
import traceback
from contextlib import asynccontextmanager

import httpx
from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError


class TokenBucket:
    def __init__(self, rpm: int):
        self._interval = 60 / max(1, rpm)
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def acquire(self):
        async with self._lock:
            now = asyncio.get_event_loop().time()
            wait = max(0.0, self._last + self._interval - now)
            if wait:
                await asyncio.sleep(wait)
            self._last = asyncio.get_event_loop().time()

class LLMClient:
    def __init__(self, api_keys, light_model_name, strong_model_name, rpm=10, use_native_json_schema=True):
        self.api_keys = api_keys
        self._key_idx = 0
        self.light_model_name = light_model_name
        self.strong_model_name = strong_model_name
        self.use_native_json_schema = use_native_json_schema
        self.bucket = TokenBucket(rpm)
        self._client = genai.Client(api_key=self.api_keys[self._key_idx])

    def _rotate_key(self):
        self._key_idx = (self._key_idx + 1) % len(self.api_keys)
        self._client = genai.Client(api_key=self.api_keys[self._key_idx])

    async def clean_up_buckets(self):
        global_idx = 0
        for key in self.api_keys:
            local_client = genai.Client(api_key=key)
            try:
                to_delete = await local_client.aio.files.list()
                for idx, f in enumerate(to_delete):
                    logging.info(f"Deleting file {global_idx}...")
                    await local_client.aio.files.delete(name=f.name)
                    global_idx += 1
            except httpx.ConnectError as e:
                logging.info(f"Error while deleting files {e}")
        logging.info(f"Deleted {global_idx} uploaded files :) Lets do the review...")

    @asynccontextmanager
    async def uploaded_file(self, path: str):
        f = self._client.files.upload(file=path)
        try:
            yield f
        finally:
            try:
                self._client.files.delete(name=f.name)
            except Exception as e:
                logging.warning("Failed to delete uploaded file: %s", f.name)
                logging.error(e)

    async def generate(self, contents, system_instruction=None, response_model=None, use_strong_model = True):
        # Backoff with key rotation on 429
        for attempt in range(6):
            await self.bucket.acquire()
            try:
                config = types.GenerateContentConfig(system_instruction=system_instruction)
                if self.use_native_json_schema and response_model is not None:
                    config.response_mime_type = "application/json"
                    config.response_schema = response_model
                model_name = self.strong_model_name if use_strong_model else self.light_model_name
                resp = await self._client.aio.models.generate_content(
                    model=model_name, contents=contents, config=config
                )
                return resp.text
            except ClientError as e:
                if e.code == 429:
                    self._rotate_key()
                    await asyncio.sleep(2 ** attempt + random.random())
                    continue
                raise
            except ServerError as e:
                if e.code == 503:
                    self._rotate_key()
                    await asyncio.sleep(5 ** attempt + random.random())
                    continue
                raise
        raise RuntimeError("Exhausted retries")