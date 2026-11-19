import argparse

def start_server():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default=10000, help="Server port")
    parser.add_argument("--retries", default=3, help="Max retries")
    return parser.parse_args()
