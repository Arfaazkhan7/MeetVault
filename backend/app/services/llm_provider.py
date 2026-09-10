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
        """Generate mock structured completion."""
        logger.warning("Using mock LLM provider - returning placeholder structured response")
        return {
            "summary": "Mock summary for testing",
            "key_takeaways": ["Mock takeaway 1", "Mock takeaway 2"],
            "topics": ["Mock topic 1", "Mock topic 2"],
            "decisions": [],
            "action_items": [],
            "questions": [],
            "answers": [],
            "suggestions": [],
            "proposals": [],
            "concerns": [],
            "agreements": [],
            "disagreements": []
        }


def get_llm_provider() -> LLMProvider:
    """Factory function that returns the appropriate LLM provider based on settings."""
    from app.core.config import settings

    provider_name = getattr(settings, "LLM_PROVIDER", "mock").lower()
    model = getattr(settings, "LLM_MODEL", "gpt-4o-mini")
    api_key = getattr(settings, "OPENAI_API_KEY", None)

    if provider_name == "openai" and api_key:
        try:
            logger.info(f"Using OpenAI LLM provider with model: {model}")
            return OpenAIProvider(api_key=api_key, model=model)
        except Exception as e:
            logger.warning(f"Failed to initialize OpenAI provider ({e}), falling back to Mock.")

    logger.info("Using Mock LLM provider (set LLM_PROVIDER=openai and OPENAI_API_KEY to use real LLM)")
    return MockLLMProvider(model="mock-model")