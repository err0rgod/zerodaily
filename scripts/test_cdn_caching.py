import time
import httpx

def test_caching(url: str, name: str, num_requests: int = 3):
    print("=" * 60)
    print(f"Testing Caching: {name}")
    print(f"Target URL:      {url}")
    print("=" * 60)
    for i in range(1, num_requests + 1):
        t0 = time.time()
        r = httpx.get(url, timeout=10.0, follow_redirects=False)
        duration_ms = (time.time() - t0) * 1000

        status = r.status_code
        cf_cache = r.headers.get("cf-cache-status", "None")
        age = r.headers.get("age", "None")
        cache_ctrl = r.headers.get("cache-control", "None")
        server = r.headers.get("server", "None")
        content_type = r.headers.get("content-type", "None")

        print(f"Request {i}:")
        print(f"  HTTP Status:     {status}")
        print(f"  Latency:         {duration_ms:.1f} ms")
        print(f"  CF-Cache-Status: {cf_cache}")
        print(f"  Age (seconds):   {age}")
        print(f"  Cache-Control:   {cache_ctrl}")
        print(f"  Content-Type:    {content_type}")
        print(f"  Server:          {server}")
        if status in [301, 302]:
            print(f"  Location:        {r.headers.get('location')}")
        print("-" * 40)
        time.sleep(1)
    print()

if __name__ == "__main__":
    test_caching("https://api.zerodaily.in/api/v1/feed", "API Feed (/api/v1/feed)")
    test_caching("https://media.zerodaily.in/images/ai/02e22737315fe005.webp", "Media Image CDN")
