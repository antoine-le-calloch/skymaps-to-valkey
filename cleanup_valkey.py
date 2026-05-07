import argparse
import redis
import os

from valkey import clear_skymap_keys
from dotenv import load_dotenv


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Cleanup existing skymap keys in ValKey.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--env", default=".env",
                   help="Path to the .env file.")

    args = parser.parse_args()
    load_dotenv(args.env)

    r = redis.Redis(
        host=os.getenv("VALKEY_HOST", "localhost"),
        port=int(os.getenv("VALKEY_PORT", "6379")),
        db=int(os.getenv("VALKEY_DB", "0")),
        decode_responses=True,
    )
    r.ping()

    n = clear_skymap_keys(r)
    print(f"Cleared {n} existing skymap:* keys.")
