from __future__ import annotations

import json
import time
import base64
from abc import ABC, abstractmethod

import requests
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.schemas.extraction import ExtractedInvoice, ExtractionResult


class ExtractionProviderError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class ExtractionProvider(ABC):
    @abstractmethod
    def extract(self, pdf_bytes: bytes) -> ExtractionResult: ...


PROMPT = """Extract only information explicitly visible in this invoice PDF.
Return null for missing values. Never infer or invent identifiers, totals, dates, PO numbers, shipment references, or tax identifiers.
Inspect the entire page, including supplier branding, header blocks, tables, and footer/summary rows. Capture a visibly labelled invoice total such as TOTAL, TOTAL DUE, AMOUNT DUE, or TOTAL USD in total_amount.
Return every field defined by the response schema. Use null when a scalar field is not explicitly present; do not omit keys.
Classify every line as BASE_FREIGHT, FUEL_SURCHARGE, DETENTION, DEMURRAGE, STORAGE, OTHER, or UNKNOWN.
Use decimal strings for amounts and quantities. Add page/source references when feasible.
List missing and uncertain fields explicitly. Currency should be an ISO code when shown or clearly denoted by a symbol.
Do not provide analysis outside the structured response."""


def generate_content_schema() -> dict:
    text = {"type": "STRING", "nullable": True}
    number = {"type": "NUMBER", "nullable": True}
    text_list = {"type": "ARRAY", "items": {"type": "STRING"}}
    line_properties = {
        "description": {"type": "STRING"}, "quantity": number, "unit_of_measure": text,
        "unit_price": number, "line_amount": {"type": "NUMBER"}, "charge_type": {"type": "STRING"},
        "shipment_reference": text, "source_reference": text,
    }
    properties = {
        "vendor_name": text, "vendor_tax_identifier": text, "invoice_number": text,
        "invoice_date": text, "due_date": text, "po_reference": text,
        "shipment_reference": text, "currency": text, "subtotal": number,
        "tax": number, "total_amount": number,
        "lines": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": line_properties, "required": list(line_properties)}},
        "missing_fields": text_list, "uncertain_fields": text_list,
        "warnings": text_list, "source_references": text_list,
    }
    return {"type": "OBJECT", "properties": properties, "required": list(properties)}


class GeminiExtractionProvider(ExtractionProvider):
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        if not self.settings.gemini_api_key:
            raise ExtractionProviderError("GEMINI_NOT_CONFIGURED", "Gemini API credentials are not configured.")

    def extract(self, pdf_bytes: bytes) -> ExtractionResult:
        started = time.perf_counter()
        try:
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{self.settings.gemini_model}:generateContent"
            response = requests.post(
                endpoint,
                headers={"x-goog-api-key": self.settings.gemini_api_key, "Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [
                        {"text": PROMPT},
                        {"inline_data": {"mime_type": "application/pdf", "data": base64.b64encode(pdf_bytes).decode("ascii")}},
                    ]}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "responseSchema": generate_content_schema(),
                        "maxOutputTokens": self.settings.gemini_max_output_tokens,
                        "temperature": 0,
                    },
                },
                timeout=(10, self.settings.gemini_timeout_ms / 1000),
            )
            if response.status_code >= 400:
                code = "GEMINI_AUTH_ERROR" if response.status_code in {401, 403} else "GEMINI_RATE_LIMIT" if response.status_code == 429 else "GEMINI_MODEL_UNAVAILABLE" if response.status_code == 404 else "GEMINI_API_ERROR"
                try:
                    provider_message = str(response.json().get("error", {}).get("message", ""))[:300]
                except ValueError:
                    provider_message = ""
                suffix = f" Provider detail: {provider_message}" if provider_message else ""
                raise ExtractionProviderError(code, f"Gemini request failed ({code}, HTTP {response.status_code}).{suffix}")
            body = response.json()
            response_text = "".join(
                part.get("text", "") for candidate in body.get("candidates", [])
                for part in candidate.get("content", {}).get("parts", []) if isinstance(part, dict)
            )
            if not response_text:
                raise ExtractionProviderError("EMPTY_PROVIDER_RESPONSE", "Gemini returned no structured extraction.")
            parsed = ExtractedInvoice.model_validate_json(response_text)
            duration_ms = round((time.perf_counter() - started) * 1000)
            raw = json.loads(response_text)
            return ExtractionResult(data=parsed, provider="google-gemini", model=self.settings.gemini_model, duration_ms=duration_ms, raw_response=raw)
        except ExtractionProviderError:
            raise
        except ValidationError as exc:
            raise ExtractionProviderError("MALFORMED_PROVIDER_RESPONSE", "Gemini returned data that failed schema validation.") from exc
        except (TimeoutError, requests.Timeout) as exc:
            raise ExtractionProviderError("GEMINI_TIMEOUT", "Gemini extraction timed out.") from exc
        except requests.RequestException as exc:
            raise ExtractionProviderError("GEMINI_NETWORK_ERROR", "Gemini could not be reached.") from exc
        except Exception as exc:
            if "timeout" in type(exc).__name__.lower():
                raise ExtractionProviderError("GEMINI_TIMEOUT", "Gemini extraction timed out.") from exc
            raise ExtractionProviderError("GEMINI_UNEXPECTED_ERROR", "Gemini extraction failed unexpectedly.") from exc


def get_extraction_provider() -> ExtractionProvider:
    return GeminiExtractionProvider()

