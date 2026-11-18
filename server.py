import argparse

def start_server():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default=9000, help="Server port")
    parser.add_argument("--max-retries", default=3, help="Max retries")
    return parser.parse_args()
