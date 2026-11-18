name: DocDrift AI Check

# Ye tab chalega jab koi Pull Request (PR) open ya update karega
on: [pull_request]

jobs:
  check-docs:
    runs-on: ubuntu-latest
    steps:
      # 1. GitHub se repo ka code download karega
      - name: Checkout Code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      # 2. GitHub ki machine me Python install karega
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      # 3. Groq library install karega
      - name: Install Dependencies
        run: pip install groq

      # 4. Tera docdrift.py script run karega
      - name: Run DocDrift Detector
        env:
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
        run: |
          git diff HEAD~1 HEAD -- *.py
          python docdrift.py HEAD~1
