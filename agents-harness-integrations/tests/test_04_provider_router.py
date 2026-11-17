import unittest
import requests
class TestRouter(unittest.TestCase):

    """def test_classification(self):
        result = requests.post("http://localhost:8080/v1/responses", json={"intent": "Say hello"})
        result.raise_for_status()
        response = result.json()
        assert response["result"] == "cheap"""
    
    def test_complete(self):
        result = requests.post("http://localhost:8080/v1/responses", json={"intent": "List all folders"})
        result.raise_for_status()
        response = result.json()
        print(response)
        assert True

if __name__ == '__main__':
    unittest.main()