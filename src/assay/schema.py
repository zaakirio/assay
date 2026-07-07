"""Target schema for extraction. This is the contract between the LLM, the
validator, and the eval harness; the JSON schema sent to llama.cpp for
constrained decoding is derived from these models."""

from pydantic import BaseModel, ConfigDict, Field


class LineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(description="Line item description as printed")
    quantity: float = Field(description="Quantity; 1 if not shown")
    unit_price: float = Field(description="Price per unit")
    amount: float = Field(description="Line total (quantity x unit_price)")


# llama.cpp's grammar converter handles $defs/anyOf from Pydantic v2 fine, so
# model_json_schema() output is sent to the server unmodified (see Extractor).
class Invoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor: str = Field(description="Supplier / issuing company name")
    invoice_number: str = Field(description="Invoice number or reference")
    invoice_date: str | None = Field(description="Issue date, ISO YYYY-MM-DD; null if absent")
    due_date: str | None = Field(description="Payment due date, ISO YYYY-MM-DD; null if absent")
    currency: str | None = Field(description="ISO 4217 code e.g. USD, EUR; null if not determinable")
    line_items: list[LineItem]
    subtotal: float | None = Field(description="Pre-tax total; null if absent")
    tax: float | None = Field(description="Total tax amount; null if absent")
    total: float = Field(description="Grand total payable")
