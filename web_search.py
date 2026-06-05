"""Real-time web search integration for OmniDoc."""
import requests
from typing import List, Dict, Any
import json

class WebSearcher:
    """Web search integration using DuckDuckGo API (free, no key needed)."""
    
    @staticmethod
    def search_duckduckgo(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        Search using DuckDuckGo (free, no API key required).
        
        Args:
            query: Search query
            max_results: Maximum number of results
            
        Returns:
            List of search results with title, link, snippet
        """
        try:
            url = "https://api.duckduckgo.com/"
            params = {
                "q": query,
                "format": "json",
                "no_redirect": 1,
                "no_html": 1,
                "t": "omnidoc"
            }
            
            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()
            
            results = []
            
            # Abstract (main result)
            if data.get("Abstract") and data.get("AbstractURL"):
                results.append({
                    "title": data.get("Heading", "Result"),
                    "link": data.get("AbstractURL"),
                    "snippet": data.get("Abstract", ""),
                    "source": "DuckDuckGo"
                })
            
            # Related results
            for item in data.get("RelatedTopics", [])[:max_results]:
                if item.get("Text") and item.get("FirstURL"):
                    results.append({
                        "title": item.get("Text", "").split(" - ")[0][:100],
                        "link": item.get("FirstURL"),
                        "snippet": item.get("Text", ""),
                        "source": "DuckDuckGo"
                    })
            
            return results[:max_results]
        
        except Exception as e:
            print(f"⚠️ DuckDuckGo search failed: {e}")
            return []

    @staticmethod
    def format_search_results(results: List[Dict[str, Any]]) -> str:
        """Format search results for inclusion in context."""
        if not results:
            return ""
        
        formatted = "\n\n[REAL-TIME WEB SEARCH RESULTS]\n"
        for i, result in enumerate(results, 1):
            formatted += f"\n{i}. {result['title']}\n"
            formatted += f"   Source: {result['link']}\n"
            formatted += f"   Summary: {result['snippet'][:200]}...\n"
        
        return formatted

    @staticmethod
    def should_use_web_search(query: str) -> bool:
        """
        Determine if web search would be useful for this query.
        Checks for keywords suggesting current information is needed.
        """
        web_keywords = [
            "latest", "current", "today", "news", "recent", "2024", "2025",
            "update", "happening", "trending", "now", "live", "breaking",
            "what's", "how to", "tutorial", "guide", "weather", "stock",
            "price", "rate", "covid", "pandemic", "election"
        ]
        
        query_lower = query.lower()
        return any(keyword in query_lower for keyword in web_keywords)
