"""Set test environment variables before the application is imported."""

import os
import tempfile

os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DEBUG": "false",
        "POSTGRES_USER": "test",
        "POSTGRES_PASSWORD": "test",
        "POSTGRES_DB": "test",
        "POSTGRES_HOST": "localhost",
        "JWT_SECRET_KEY": "test-secret-key-not-for-production",
        # The fence: redirect every Chroma store the suite builds — injected or
        # fallen through to the real factory — into a throwaway temp dir, so no
        # test can ever write into the development chroma/ directory.
        "CHROMA_PERSIST_DIR": tempfile.mkdtemp(prefix="nexus-test-chroma-"),
        # Offline by default: no test may make a billable, networked OpenAI call.
        # A test needing a provider must inject a fake; a failure here means a fake
        # is missing, not that this key should be restored.
        "OPENAI_API_KEY": "",
    }
)
