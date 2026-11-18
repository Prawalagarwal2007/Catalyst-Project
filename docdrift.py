import os
import sys
import re
import json
import hashlib
import subprocess
import requests
from groq import Groq

CACHE_FILE = ".doc_cache.json"

def get_code_changes():
    base_sha = os.environ.get("BASE_SHA")
    head_sha = os.environ.get("HEAD_SHA")
    
    if base_sha and head_sha:
        cmd = ["git", "diff", "-U0", base_sha, head_sha, "--", "*.py", "*.js", "*.ts", "*.go", "*.rs", "*.java"]
    else:
        cmd = ["git", "diff", "-U0", "HEAD~1", "HEAD", "--", "*.py", "*.js", "*.ts", "*.go", "*.rs", "*.java"]
        
    diff_text = subprocess.check_output(cmd, text=True)
    if not diff_text.strip():
        return None, []

    keywords = set(re.findall(r'--[a-zA-Z0-9_-]+|[a-zA-Z_][a-zA-Z0-9_]{2,}|\b\d+\b', diff_text))
    stop_words = {"diff", "git", "index", "def", "return", "import", "from", "class", "self", "true", "false", "none"}
    clean_keywords = [k for k in keywords if k.lower() not in stop_words]
    
    return diff_text, clean_keywords

def index_documentation(doc_files):
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)

    new_cache = {}
    all_chunks = []

    for filepath in doc_files:
        if not os.path.exists(filepath):
            continue
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if filepath in cache and cache[filepath]["hash"] == file_hash:
            new_cache[filepath] = cache[filepath]
            all_chunks.extend(cache[filepath]["chunks"])
            continue

        chunks = []
        for idx, line in enumerate(content.split("\n"), start=1):
            clean = line.strip()
            if len(clean) > 10 and not clean.startswith("#"):
                chunks.append({
                    "doc_file": filepath,
                    "line_number": idx,
                    "text": clean
                })
        
        new_cache[filepath] = {"hash": file_hash, "chunks": chunks}
        all_chunks.extend(chunks)

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(new_cache, f, indent=2)

    return all_chunks

def find_relevant_docs(chunks, keywords, top_k=5):
    scored_chunks = []
    for chunk in chunks:
        score = 0
        text_lower = chunk["text"].lower()
        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower in text_lower:
                score += 5
                if f"`{kw_lower}`" in text_lower:
                    score += 10
        if "|" in chunk["text"] and score > 0:
            score += 3
            
        if score > 0:
            scored_chunks.append((score, chunk))

    scored_chunks.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored_chunks[:top_k]]

def check_drift_with_ai(diff_text, candidate_chunks):
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("ERROR: GROQ_API_KEY Secret is missing in GitHub Settings!")
        sys.exit(1)

    client = Groq(api_key=api_key)

    prompt = f"""
You are a strict CI/CD Documentation Drift Detector.
Compare the CODE DIFF below with the CANDIDATE DOCUMENTATION SENTENCES.

CODE DIFF:
{diff_text}

CANDIDATE DOCUMENTATION LINES:
{json.dumps(candidate_chunks, indent=2)}

Rules:
1. Only flag a documentation line if the code diff directly makes it FACTUALLY WRONG or OUTDATED (e.g., changed default value, renamed CLI flag, removed option, or a config table missing a new option).
2. Return strict JSON with a "drifts" list. For each drift include:
   - "doc_file": filename
   - "line_number": exact line number
   - "old_doc_sentence": exact outdated line
   - "code_change_summary": which file/line in code caused this
   - "suggested_fix": updated documentation line
"""

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.0
    )

    return json.loads(response.choices[0].message.content)

def post_pr_comment(drifts):
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    pr_number = os.environ.get("PR_NUMBER")
    
    if not (token and repo and pr_number):
        return

    body = "## 🚨 DocDrift AI Alert: Outdated Documentation Detected!\n\n"
    body += "Your code change modified behavior that is documented in the repository, making the following documentation lines **factually wrong**:\n\n"
    body += "| 📍 Doc File & Line | 🔧 Code Change Cause | ❌ Outdated Doc Sentence | ✅ AI Suggested Fix |\n"
    body += "| :--- | :--- | :--- | :--- |\n"
    
    for d in drifts:
        doc_loc = f"`{d.get('doc_file')}` (Line {d.get('line_number')})"
        cause = d.get('code_change_summary', '')
        old_s = d.get('old_doc_sentence', '').replace('|', '\\|')
        fix_s = d.get('suggested_fix', '').replace('|', '\\|')
        body += f"| {doc_loc} | {cause} | `{old_s}` | `{fix_s}` |\n"

    body += "\n---\n*⚡ Powered by Open-Weight `Llama-3.1-8B-Instant` + SHA-256 Incremental Doc Indexer*"

    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    requests.post(url, headers=headers, json={"body": body})

def main():
    print("🔍 Scanning code changes (git diff)...")
    diff_text, keywords = get_code_changes()
    
    if not diff_text:
        print("✅ No code changes detected (Zero False Alarms!).")
        return

    print(f"🔑 Extracted Code Clues: {keywords}")
    doc_files = [f for f in os.listdir(".") if f.endswith(".md")]
    chunks = index_documentation(doc_files)
    
    candidates = find_relevant_docs(chunks, keywords)
    if not candidates:
        print("✅ No matching documentation lines affected by this change.")
        return

    print(f"📄 Found {len(candidates)} candidate doc lines. Asking Llama-3.1-8B...")
    result = check_drift_with_ai(diff_text, candidates)
    
    if result and result.get("drifts"):
        drifts = result["drifts"]
        print("\n🚨 DOCUMENTATION DRIFT DETECTED! Posting comment to PR...")
        post_pr_comment(drifts)
        for d in drifts:
            print(f"📍 {d.get('doc_file')} (Line {d.get('line_number')}): {d.get('old_doc_sentence')} -> {d.get('suggested_fix')}")
        # Fail CI check intentionally so maintainer notices the outdated docs!
        sys.exit(1)
    else:
        print("✅ Documentation is completely up-to-date!")

if __name__ == "__main__":
    main()
