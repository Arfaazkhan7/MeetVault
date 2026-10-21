import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
import json

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Abstract base class for LLM providers to allow easy replacement."""
    
    @abstractmethod
    def generate_completion(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> str:
        """Generate text completion from the LLM."""
        pass
    
    @abstractmethod
    def generate_structured_completion(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        schema: Optional[Dict[str, Any]] = None,
        temperature: float = 0.7
    ) -> Dict[str, Any]:
        """Generate structured JSON completion from the LLM."""
        pass


class OpenAIProvider(LLMProvider):
    """OpenAI GPT-based LLM provider."""
    
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        """
        Initialize OpenAI provider.
        
        Args:
            api_key: OpenAI API key
            model: Model name (default: gpt-4o-mini)
        """
        try:
            import openai
            self.client = openai.OpenAI(api_key=api_key)
            self.model = model
            logger.info(f"Initialized OpenAI provider with model: {model}")
        except ImportError:
            logger.error("OpenAI package not installed")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI provider: {e}")
            raise
    
    def generate_completion(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> str:
        """Generate text completion from OpenAI."""
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"OpenAI completion failed: {e}")
            raise
    
    def generate_structured_completion(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        schema: Optional[Dict[str, Any]] = None,
        temperature: float = 0.7
    ) -> Dict[str, Any]:
        """Generate structured JSON completion from OpenAI."""
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            if schema:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    response_format={"type": "json_object"}
                )
            else:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature
                )
            
            content = response.choices[0].message.content
            return json.loads(content)
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            raise ValueError(f"Invalid JSON response from LLM: {e}")
        except Exception as e:
            logger.error(f"OpenAI structured completion failed: {e}")
            raise


class MockLLMProvider(LLMProvider):
    """Mock LLM provider for testing and development.

    Generates a deterministic grounded answer that directly references
    content from the provided context prompt, ensuring tests can assert
    that the answer is grounded in evidence.
    """
    
    def __init__(self, model: str = "mock-model"):
        """Initialize mock provider."""
        self.model = model
        logger.info(f"Initialized Mock LLM provider with model: {model}")
    
    def generate_completion(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> str:
        """Generate a mock completion that references evidence content.
        
        Inspects the prompt for EVIDENCE CONTEXT blocks and constructs a
        grounded answer mentioning the key evidence keywords so tests can
        assert that the answer is evidence-backed.
        """
        # Extract the first evidence excerpt from the prompt to reference
        evidence_lines = [
            line.strip() for line in prompt.splitlines()
            if line.strip().startswith("Excerpt:") or line.strip().startswith("- Excerpt:")
        ]
        
        if evidence_lines:
            # Reference the first evidence excerpt in our answer
            first_excerpt = evidence_lines[0].replace("Excerpt:", "").replace("- Excerpt:", "").strip()
            # Truncate to a readable length
            truncated = first_excerpt[:200] if len(first_excerpt) > 200 else first_excerpt
            return (
                f"Based on the meeting evidence retrieved from memory: {truncated} "
                f"The meeting transcripts and decisions document this clearly, as referenced in the evidence below."
            )
        
        # No evidence found — produce insufficient evidence signal
        if "EVIDENCE CONTEXT" in prompt and ("No relevant" in prompt or len(prompt) < 400):
            return "__INSUFFICIENT_EVIDENCE__"
        
        return (
            "Based on the available mock meeting memory, the evidence suggests this topic was discussed "
            "across multiple meetings. Please refer to the cited evidence for details."
        )
    
    def generate_structured_completion(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        schema: Optional[Dict[str, Any]] = None,
        temperature: float = 0.7
    ) -> Dict[str, Any]:
        """Generate dynamic mock structured completion grounded in prompt transcript segments."""
        logger.info("Mock LLM Provider generating structured completion from prompt transcript")
        
        # Parse transcript lines in format: [start - end] SPEAKER: text
        decisions = []
        action_items = []
        questions = []
        concerns = []
        topics = []
        commitments = []
        summary_parts = []

        lines = prompt.splitlines()
        for line in lines:
            line_str = line.strip()
            if not line_str or not line_str.startswith("["):
                continue
            
            # Extract timestamp range, speaker, text
            try:
                bracket_end = line_str.find("]")
                if bracket_end != -1:
                    ts_part = line_str[1:bracket_end]
                    rest = line_str[bracket_end+1:].strip()
                    speaker_part, text_part = rest.split(":", 1) if ":" in rest else ("SPEAKER", rest)
                    speaker_label = speaker_part.strip()
                    text = text_part.strip()

                    # Parse timestamps
                    ts_split = ts_part.replace("s", "").split("-")
                    start_ts = float(ts_split[0].strip()) if ts_split else 0.0
                    
                    summary_parts.append(text)

                    # Dynamic classification based on intent keywords in text
                    lower_text = text.lower()
                    ev_dict = [{
                        "timestamp": start_ts,
                        "speaker": speaker_label,
                        "content": text
                    }]

                    if any(k in lower_text for k in ["decid", "agreed", "launch to", "move", "confirm", "set"]):
                        decisions.append({
                            "title": text,
                            "status": "confirmed",
                            "type": "agreement",
                            "confidence": "high",
                            "speaker": speaker_label,
                            "evidence": ev_dict
                        })

                    if any(k in lower_text for k in ["will", "i'll", "checklist", "finish", "send", "action", "task", "by "]):
                        action_items.append({
                            "title": text,
                            "description": text,
                            "assignee": speaker_label,
                            "priority": "high" if "urgent" in lower_text else "medium",
                            "deadline": None,
                            "evidence": ev_dict
                        })
                        commitments.append({
                            "person": speaker_label,
                            "commitment": text,
                            "evidence": ev_dict
                        })

                    if "?" in text or any(k in lower_text for k in ["what", "how", "who", "when", "why", "can you"]):
                        questions.append({
                            "question": text,
                            "speaker": speaker_label,
                            "evidence": ev_dict
                        })

                    if any(k in lower_text for k in ["risk", "concern", "delay", "issue", "problem", "need another"]):
                        concerns.append({
                            "title": text,
                            "concern": text,
                            "severity": "high" if "critical" in lower_text else "medium",
                            "evidence": ev_dict
                        })
            except Exception as e:
                logger.debug(f"Skipping line parse in mock provider: {e}")

        if not summary_parts:
            summary_text = "Meeting transcript analyzed successfully."
        else:
            summary_text = "The team discussed: " + " ".join(summary_parts[:4])

        if not topics:
            topics = [
                {"name": "Project Strategy", "importance": "high"},
                {"name": "Execution & Delivery", "importance": "medium"}
            ]

        return {
            "summary": summary_text,
            "key_takeaways": summary_parts[:3] if summary_parts else ["Meeting completed successfully"],
            "topics": topics,
            "decisions": decisions,
            "action_items": action_items,
            "tasks": action_items,
            "questions": questions,
            "answers": [],
            "suggestions": [],
            "proposals": decisions,
            "concerns": concerns,
            "risks": concerns,
            "commitments": commitments,
            "agreements": decisions,
            "disagreements": []
        }


class CloudflareLLMProvider(LLMProvider):
    """Use the Workers AI binding; never silently substitute mock analysis."""

    def __init__(self, model: str):
        self.model = model

    def generate_completion(self, prompt, system_prompt=None, temperature=0.7, max_tokens=None) -> str:
        from workers import env
        from pyodide.ffi import run_sync

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        result = run_sync(env.AI.run(self.model, {
            "messages": messages, "temperature": temperature,
            "max_tokens": max_tokens or 2048,
        }))
        if hasattr(result, "to_py"):
            result = result.to_py()
        response = result.get("response") if isinstance(result, dict) else getattr(result, "response", None)
        if not isinstance(response, str) or not response.strip():
            raise RuntimeError("Workers AI returned no completion")
        return response

    def generate_structured_completion(self, prompt, system_prompt=None, schema=None, temperature=0.7) -> Dict[str, Any]:
        instruction = (system_prompt or "") + "\nReturn only one valid JSON object, without Markdown fences."
        if schema:
            instruction += "\nRequired JSON schema: " + json.dumps(schema)
        response = self.generate_completion(prompt, instruction, temperature)
        # Some chat models wrap valid JSON in a Markdown code fence.
        if response.strip().startswith("```"):
            response = "\n".join(response.strip().splitlines()[1:-1])
        result = json.loads(response)
        if not isinstance(result, dict):
            raise ValueError("Workers AI must return a JSON object")
        return result


def get_llm_provider() -> LLMProvider:
    """Factory function that returns the appropriate LLM provider based on settings."""
    from app.core.config import settings

    provider_name = getattr(settings, "LLM_PROVIDER", "mock").lower()
    model = getattr(settings, "LLM_MODEL", "gpt-4o-mini")
    api_key = getattr(settings, "OPENAI_API_KEY", None)

    if provider_name == "cloudflare":
        from app.core.runtime import IS_WORKERS
        if not IS_WORKERS:
            raise RuntimeError("LLM_PROVIDER=cloudflare requires the Cloudflare Workers runtime")
        return CloudflareLLMProvider(model=model)

    if provider_name == "openai" and api_key:
        try:
            logger.info(f"Using OpenAI LLM provider with model: {model}")
            return OpenAIProvider(api_key=api_key, model=model)
        except Exception as e:
            logger.warning(f"Failed to initialize OpenAI provider ({e}), falling back to Mock.")

    logger.info("Using Mock LLM provider (set LLM_PROVIDER=openai and OPENAI_API_KEY to use real LLM)")
    return MockLLMProvider(model="mock-model")
