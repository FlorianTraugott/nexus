"""Set test environment variables before the application is imported."""

import os

os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DEBUG": "false",
        "POSTGRES_USER": "test",
        "POSTGRES_PASSWORD": "test",
        "POSTGRES_DB": "test",
        "POSTGRES_HOST": "localhost",
        "JWT_SECRET_KEY": "test-secret-key-not-for-production",
    }
)
