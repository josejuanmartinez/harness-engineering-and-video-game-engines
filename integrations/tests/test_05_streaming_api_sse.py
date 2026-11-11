import unittest
import requests
from requests import Response
class TestRouter(unittest.TestCase):
    
    def test_streaming(self):
        r: Response = None
        with requests.post("http://localhost:8080/v1/chat", json={"message": "List all folders"}, headers={"Accept": "text/event-stream"}, stream=True, timeout=(5,60)) as r:
            r.raise_for_status()
            for line in r:
                print(line)
                print()

if __name__ == '__main__':
    unittest.main()