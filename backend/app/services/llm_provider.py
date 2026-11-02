import json
import httpx
from typing import List, Dict, Any, Optional, AsyncGenerator
from app.core.config import settings

class LLMProvider:
    """
    Switchable LLM client supporting Google Gemini, Mistral API, and Mock/Offline Engine.
    Configured via LLM_PROVIDER in .env.
    """

    @staticmethod
    async def call_gemini(
        system_instruction: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        api_key = settings.GEMINI_API_KEY
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not configured.")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.GEMINI_MODEL}:generateContent?key={api_key}"
        
        # Build contents
        contents = []
        for m in messages:
            role = "user" if m["role"] == "user" else "model"
            contents.append({
                "role": role,
                "parts": [{"text": m["content"]}]
            })

        # Format tools for Gemini
        gemini_tools = []
        if tools:
            function_declarations = []
            for t in tools:
                function_declarations.append({
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t.get("parameters", {"type": "OBJECT", "properties": {}})
                })
            gemini_tools = [{"functionDeclarations": function_declarations}]

        payload = {
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "contents": contents,
        }
        if gemini_tools:
            payload["tools"] = gemini_tools

        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(url, json=payload)
            if res.status_code != 200:
                raise ValueError(f"Gemini API error ({res.status_code}): {res.text}")
            
            data = res.json()
            candidate = data.get("candidates", [{}])[0]
            parts = candidate.get("content", {}).get("parts", [])
            
            text_response = ""
            tool_calls = []
            for part in parts:
                if "text" in part:
                    text_response += part["text"]
                elif "functionCall" in part:
                    fc = part["functionCall"]
                    tool_calls.append({
                        "name": fc.get("name"),
                        "args": fc.get("args", {})
                    })

            return {
                "text": text_response,
                "tool_calls": tool_calls
            }

    @staticmethod
    async def call_mistral(
        system_instruction: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        api_key = settings.MISTRAL_API_KEY
        if not api_key:
            raise ValueError("MISTRAL_API_KEY is not configured.")

        url = "https://api.mistral.ai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        formatted_messages = [{"role": "system", "content": system_instruction}]
        for m in messages:
            formatted_messages.append({"role": m["role"], "content": m["content"]})

        payload = {
            "model": settings.MISTRAL_MODEL,
            "messages": formatted_messages
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(url, json=payload, headers=headers)
            if res.status_code != 200:
                raise ValueError(f"Mistral API error ({res.status_code}): {res.text}")
            data = res.json()
            choice = data["choices"][0]
            return {
                "text": choice["message"]["content"],
                "tool_calls": []
            }

