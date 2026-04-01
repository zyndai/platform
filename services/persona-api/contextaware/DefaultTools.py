import requests
from bs4 import BeautifulSoup
from urllib.parse import quote
from ddgs import DDGS
from googlesearch import search as google_search
import datetime
import platform
import os
import math


def internet_search(query, engine="google", images=False, num_results=5):
    """
    Perform an internet search using Google or DuckDuckGo.

    Args:
        query (str): Search query
        engine (str): "google" (default) or "duckduckgo"
        images (bool): If True, returns image results
        num_results (int): Number of results to return

    Returns:
        list[dict]: Parsed search results
    """
    results = []

    if engine.lower() == "google":
        if images:
            url = f"https://www.google.com/search?tbm=isch&q={quote(query)}"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

            response = requests.get(url, headers=headers)
            soup = BeautifulSoup(response.text, "html.parser")

            for img in soup.find_all("img")[1:num_results+1]:
                src = img.get("src")
                if src and src.startswith("http"):
                    results.append({"image_url": src})
        else:
            for res in google_search(query, num_results=num_results, advanced=True):
                results.append({
                    "title": res.title,
                    "link": res.url,
                    "snippet": res.description
                })

    elif engine.lower() == "duckduckgo":
        with DDGS() as ddgs:
            if images:
                ddg_results = list(ddgs.images(query, max_results=num_results))
                for res in ddg_results:
                    results.append({"image_url": res.get("image")})
            else:
                ddg_results = list(ddgs.text(query, max_results=num_results))
                for res in ddg_results:
                    results.append({
                        "title": res.get("title"),
                        "link": res.get("href"),
                        "snippet": res.get("body")
                    })
    else:
        raise ValueError("Engine must be 'google' or 'duckduckgo'")

    # Fallback to duckduckgo if google returned nothing
    if not results and engine.lower() == "google":
        return internet_search(query, engine="duckduckgo", images=images, num_results=num_results)

    return results


def webpage_scrape(url, max_length=5000):
    """
    Scrape text content from a webpage.

    Args:
        url (str): URL to scrape
        max_length (int): Max characters to return

    Returns:
        dict: Title and text content of the page
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    response = requests.get(url, headers=headers, timeout=10)
    soup = BeautifulSoup(response.text, "html.parser")

    # Remove script and style tags
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    text = soup.get_text(separator="\n", strip=True)

    return {
        "title": title,
        "url": url,
        "content": text[:max_length]
    }


def get_current_time(timezone=None):
    """
    Get the current date and time.

    Args:
        timezone (str): Optional timezone name (not used, returns UTC and local)

    Returns:
        dict: Current time info
    """
    now = datetime.datetime.now()
    utc_now = datetime.datetime.utcnow()

    return {
        "local_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "utc_time": utc_now.strftime("%Y-%m-%d %H:%M:%S"),
        "timestamp": int(now.timestamp()),
        "day_of_week": now.strftime("%A"),
    }


def read_file(file_path, max_lines=100):
    """
    Read contents of a local file.

    Args:
        file_path (str): Path to the file
        max_lines (int): Max number of lines to return

    Returns:
        dict: File info and content
    """
    path = os.path.expanduser(file_path)
    if not os.path.exists(path):
        return {"error": f"File not found: {file_path}"}

    if not os.path.isfile(path):
        return {"error": f"Not a file: {file_path}"}

    size = os.path.getsize(path)

    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        return {"error": "Cannot read binary file as text"}

    return {
        "file_path": path,
        "size_bytes": size,
        "total_lines": len(lines),
        "content": "".join(lines[:max_lines]),
        "truncated": len(lines) > max_lines,
    }


def calculate(expression):
    """
    Evaluate a math expression safely.

    Args:
        expression (str): Math expression like "2 + 2" or "sqrt(16)"

    Returns:
        dict: The result or error
    """
    allowed_names = {
        "abs": abs, "round": round, "min": min, "max": max,
        "sum": sum, "pow": pow, "int": int, "float": float,
        "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos,
        "tan": math.tan, "log": math.log, "log10": math.log10,
        "pi": math.pi, "e": math.e, "ceil": math.ceil, "floor": math.floor,
    }

    try:
        result = eval(expression, {"__builtins__": {}}, allowed_names)
        return {"expression": expression, "result": result}
    except Exception as e:
        return {"expression": expression, "error": str(e)}


def get_system_info():
    """
    Get basic system information.

    Returns:
        dict: System info like OS, architecture, etc.
    """
    return {
        "os": platform.system(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "hostname": platform.node(),
    }


# All default tools collected here
default_tools = {internet_search, webpage_scrape, get_current_time, read_file, calculate, get_system_info}